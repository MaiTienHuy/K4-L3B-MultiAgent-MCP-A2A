"""Entity & Customer Agent --- Lê Việt Hoàng phụ trách.

Nhiệm vụ (PHAN_CONG_4_NGUOI.md Pha 3, KE_HOACH_MILESTONE.md M2):
  - resolve order của case: exact lookup trước, chỉ mở rộng có điều kiện;
  - loại candidate bằng dữ kiện kiểm chứng được, không chọn tuỳ tiện;
  - dựng customer context (`customer_unique_id`, `related_order_ids`);
  - trả trạng thái mơ hồ (`ambiguous`) khi chưa đủ căn cứ.

Tool được cấp (discovery thật, khớp PHAN_CONG_4_NGUOI.md):
  - `get_order(case_id, order_id)`
  - `get_customer_history(case_id, customer_unique_id)`

Nguyên tắc bắt buộc (huong-dan.txt Pha 3):
  - mọi MCP call truyền đúng `case_id` (sai -> 403 Forbidden);
  - KHÔNG tự tạo/sửa `evidence_ref`, chỉ dùng ref do MCP trả về;
  - ghi `tool_result_consumed` sau mỗi lần tiêu thụ evidence;
  - không hardcode đáp án theo `case_id`.

Ghi chú hợp đồng: `workflow.py` (Mai Tiến Huy) đọc trực tiếp các thuộc tính
`status, resolved_order_ids, rejected_candidates, order_ids, item_ids, seller_ids,
payment_references, shipment_ids, customer_unique_id, related_order_ids, confidence,
evidence_refs` trên object trả về. Trường `notes` là phần bổ sung của agent này
(không bắt buộc), dùng để ghi lại lý do/điểm chưa chắc chắn cho verifier.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ..mcp_gateway import EvidenceGateway
from ..trace import TraceWriter

ACTOR = "entity-agent"
TARGET_COORDINATOR = "coordinator"

TOOL_ORDER = "get_order"
TOOL_CUSTOMER_HISTORY = "get_customer_history"

# Ngân sách tra cứu cho một case (efficiency được tính theo call thật).
MAX_ORDER_LOOKUPS = 3

# Ngưỡng confidence theo ARCHITECTURE.md §3, không tự đổi lệch tài liệu chung.
CONFIDENCE_CLAIMED_EXACT = 0.85
CONFIDENCE_RESOLVED_ALTERNATE = 0.65
CONFIDENCE_AMBIGUOUS = 0.5
CONFIDENCE_UNRESOLVED = 0.0
CONFIDENCE_NOT_FOUND_BRANCH = 0.65

# Order id thật của bộ Olist là chuỗi hex 32 ký tự; candidate dạng "candidate-00X"
# không thể là order id hợp lệ nên bị loại bằng quy tắc tất định, không tốn call.
ORDER_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")

HISTORY_TIMESTAMP_FIELDS = (
    "order_purchase_timestamp",
    "order_approved_at",
    "order_delivered_carrier_date",
    "order_delivered_customer_date",
    "order_estimated_delivery_date",
)


@dataclass
class EntityResult:
    """Kết quả bàn giao của entity agent cho coordinator.

    `status` dùng đúng enum của `l3b-output-v2.schema.json#/entity_resolution`:
    `resolved | ambiguous | not_found`.
    """

    case_id: str
    status: str
    resolved_order_ids: list[str] = field(default_factory=list)
    rejected_candidates: list[str] = field(default_factory=list)
    order_ids: list[str] = field(default_factory=list)
    item_ids: list[str] = field(default_factory=list)
    seller_ids: list[str] = field(default_factory=list)
    payment_references: list[str] = field(default_factory=list)
    shipment_ids: list[str] = field(default_factory=list)
    customer_unique_id: str | None = None
    related_order_ids: list[str] = field(default_factory=list)
    confidence: float = CONFIDENCE_UNRESOLVED
    ambiguous: bool = False
    evidence_refs: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _text(value: Any) -> str:
    """Chuẩn hoá giá trị về chuỗi đã strip; trả '' nếu không phải chuỗi."""
    if isinstance(value, str):
        return value.strip()
    return ""


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _candidate_order(case: dict[str, Any]) -> list[str]:
    """Danh sách candidate theo thứ tự ưu tiên: claimed order trước, rồi tới input."""
    request = case.get("customer_request") or {}
    claimed = _text(request.get("claimed_order_id"))
    raw = case.get("candidate_order_ids") or []
    candidates = [claimed] if claimed else []
    if isinstance(raw, list):
        candidates.extend(_text(item) for item in raw)
    return _dedupe(candidates)


def _order_records(records: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return records


def _rank_alternates(
    case: dict[str, Any], records: dict[str, dict[str, Any]], claimed: str | None
) -> list[str]:
    """Xếp hạng candidate đã resolve khi không có exact match với claimed order.

    Tiêu chí quan sát được, không dùng suy luận ẩn: order chưa bị loại, có
    timestamp mua hàng và `customer_id` đọc được, rồi tới thứ tự xuất hiện.
    """
    order = [order_id for order_id in _candidate_order(case) if order_id in records]
    for order_id in records:
        if order_id not in order:
            order.append(order_id)

    def sort_key(order_id: str) -> tuple[int, str]:
        data = records.get(order_id) or {}
        purchase = _text(data.get("order_purchase_timestamp"))
        customer = _text(data.get("customer_id"))
        completeness = int(bool(purchase)) + int(bool(customer))
        if order_id == claimed:
            completeness += 1
        return (-completeness, order_id)

    return sorted(order, key=sort_key)


def _history_conflict(
    record: dict[str, Any], history_orders: list[Any], order_id: str
) -> list[str]:
    """So sánh mốc thời gian của cùng một order giữa `get_order` và customer history.

    Bộ dữ liệu có case trả về cùng `order_id` với timestamp khác nhau giữa hai
    nguồn; đây là mâu thuẫn nguồn cần được ghi nhận (không tự chọn nguồn nào).
    """
    conflicting: list[str] = []
    for entry in history_orders:
        if not isinstance(entry, dict) or _text(entry.get("order_id")) != order_id:
            continue
        for field_name in HISTORY_TIMESTAMP_FIELDS:
            left = _text(record.get(field_name))
            right = _text(entry.get(field_name))
            if left and right and left != right and field_name not in conflicting:
                conflicting.append(field_name)
    return conflicting


async def _lookup_order(
    gateway: EvidenceGateway,
    case_id: str,
    order_id: str,
    trace: TraceWriter,
    evidence_refs: list[str],
) -> dict[str, Any] | None:
    """Tra một order qua MCP; trả `None` khi order không tồn tại.

    Gateway raise `RuntimeError` cho order id không có dữ liệu, nên lỗi này được
    coi là "candidate bị loại" chứ không phải lỗi hệ thống.
    """
    try:
        evidence = await gateway.call(TOOL_ORDER, case_id=case_id, order_id=order_id)
    except RuntimeError:
        return None
    data = evidence.get("data") if isinstance(evidence.get("data"), dict) else {}
    evidence_ref = _text(evidence.get("evidence_ref"))
    if evidence_ref:
        evidence_refs.append(evidence_ref)
    attributes: dict[str, Any] = {"order_id": order_id}
    domain = _text(evidence.get("domain"))
    if domain:
        attributes["domain"] = domain
    trace.emit(
        case_id=case_id,
        event_type="tool_result_consumed",
        actor=ACTOR,
        target=TARGET_COORDINATOR,
        tool_name=TOOL_ORDER,
        evidence_refs=[evidence_ref] if evidence_ref else None,
        attributes=attributes,
    )
    if not data or _text(data.get("order_id")) != order_id:
        return None
    return data


async def _fetch_customer_history(
    gateway: EvidenceGateway,
    case_id: str,
    customer_unique_id: str,
    trace: TraceWriter,
    evidence_refs: list[str],
) -> dict[str, Any] | None:
    """Tra customer context qua MCP; trả `None` khi không lấy được evidence."""
    try:
        evidence = await gateway.call(
            TOOL_CUSTOMER_HISTORY, case_id=case_id, customer_unique_id=customer_unique_id
        )
    except RuntimeError:
        return None
    data = evidence.get("data") if isinstance(evidence.get("data"), dict) else {}
    evidence_ref = _text(evidence.get("evidence_ref"))
    if evidence_ref:
        evidence_refs.append(evidence_ref)
    orders = data.get("orders") if isinstance(data.get("orders"), list) else []
    attributes: dict[str, Any] = {
        "customer_unique_id": customer_unique_id,
        "order_count": len(orders),
    }
    domain = _text(evidence.get("domain"))
    if domain:
        attributes["domain"] = domain
    trace.emit(
        case_id=case_id,
        event_type="tool_result_consumed",
        actor=ACTOR,
        target=TARGET_COORDINATOR,
        tool_name=TOOL_CUSTOMER_HISTORY,
        evidence_refs=[evidence_ref] if evidence_ref else None,
        attributes=attributes,
    )
    return data or None


async def run(
    case: dict[str, Any], gateway: EvidenceGateway, trace: TraceWriter
) -> EntityResult:
    """Resolve entity của một case rồi bàn giao `EntityResult` cho coordinator."""
    case_id = _text(case.get("case_id"))
    if not case_id:
        raise ValueError("case is missing case_id")

    request = case.get("customer_request") or {}
    claimed = _text(request.get("claimed_order_id")) or None
    hint = _text(case.get("customer_unique_id_hint")) or None
    scope = case.get("investigation_scope") or {}
    include_history = scope.get("include_customer_history", True) is not False
    candidates = _candidate_order(case)

    trace.emit(
        case_id=case_id,
        event_type="task_assigned",
        actor=ACTOR,
        target=ACTOR,
        attributes={
            "task": "entity_resolution",
            "candidate_count": len(candidates),
            "claimed_order_present": claimed is not None,
        },
    )

    evidence_refs: list[str] = []
    notes: list[str] = []
    rejected: list[str] = []
    records: dict[str, dict[str, Any]] = {}
    lookups = 0

    for order_id in candidates:
        is_claimed = claimed is not None and order_id == claimed
        if not is_claimed and not ORDER_ID_PATTERN.fullmatch(order_id):
            # Quy tắc tất định: candidate không có dạng order id của bộ dữ liệu
            # nên bị loại mà không tiêu tốn MCP call (efficiency).
            rejected.append(order_id)
            notes.append(f"candidate_rejected_invalid_shape:{order_id}")
            continue
        if lookups >= MAX_ORDER_LOOKUPS:
            rejected.append(order_id)
            notes.append(f"candidate_not_probed_budget:{order_id}")
            continue
        lookups += 1
        data = await _lookup_order(gateway, case_id, order_id, trace, evidence_refs)
        if data is None:
            rejected.append(order_id)
            notes.append(f"candidate_rejected_lookup_failed:{order_id}")
            continue
        records[order_id] = data

    # ------------------------------------------------------------------ quyết định
    if claimed and claimed in records:
        status = "resolved"
        confidence = CONFIDENCE_CLAIMED_EXACT
        resolved = [claimed]
        for order_id in records:
            if order_id != claimed:
                rejected.append(order_id)
                notes.append(f"candidate_rejected_not_claimed_order:{order_id}")
    elif len(records) == 1:
        status = "resolved"
        confidence = CONFIDENCE_RESOLVED_ALTERNATE
        resolved = list(records)
        notes.append("resolved_without_claimed_exact_match")
    elif len(records) > 1:
        status = "ambiguous"
        confidence = CONFIDENCE_AMBIGUOUS
        resolved = _rank_alternates(case, records, claimed)
        notes.append("multiple_candidates_resolved")
    else:
        status = "not_found"
        confidence = CONFIDENCE_UNRESOLVED
        resolved = []

    # ---------------------------------------------------------- customer context
    customer_unique_id: str | None = None
    related_order_ids: list[str] = []
    history_verified = False

    if not include_history:
        notes.append("customer_history_skipped_by_scope")
        customer_unique_id = hint
    elif not hint:
        notes.append("customer_unique_id_hint_missing")
    else:
        history = await _fetch_customer_history(gateway, case_id, hint, trace, evidence_refs)
        if history is None:
            notes.append("customer_history_unavailable")
            # hint là dữ liệu do đề cung cấp, không phải giá trị tự suy diễn.
            customer_unique_id = hint
            if status == "resolved":
                confidence = min(confidence, CONFIDENCE_NOT_FOUND_BRANCH)
        else:
            orders = history.get("orders") if isinstance(history.get("orders"), list) else []
            history_ids = _dedupe(
                [_text(entry.get("order_id")) for entry in orders if isinstance(entry, dict)]
            )
            related_order_ids = history_ids
            if resolved and resolved[0] in history_ids:
                customer_unique_id = _text(history.get("customer_unique_id")) or hint
                history_verified = True
                conflict_fields = _history_conflict(
                    records.get(resolved[0]) or {}, orders, resolved[0]
                )
                if conflict_fields:
                    notes.append("order_history_conflict:" + ",".join(conflict_fields))
            else:
                notes.append("customer_history_mismatch")
                if status == "resolved":
                    confidence = min(confidence, CONFIDENCE_RESOLVED_ALTERNATE)

    result = EntityResult(
        case_id=case_id,
        status=status,
        resolved_order_ids=_dedupe(resolved)[:20],
        rejected_candidates=_dedupe(rejected)[:20],
        order_ids=_dedupe(resolved)[:20],
        customer_unique_id=customer_unique_id,
        related_order_ids=_dedupe(related_order_ids)[:20],
        confidence=round(confidence, 2),
        ambiguous=status == "ambiguous",
        evidence_refs=_dedupe(evidence_refs)[:20],
        notes=notes[:20],
    )

    handoff_attributes: dict[str, Any] = {
        "resolved_order_count": len(result.resolved_order_ids),
        "rejected_candidate_count": len(result.rejected_candidates),
        "confidence": result.confidence,
        "ambiguous": result.ambiguous,
        "customer_history_verified": history_verified,
    }
    if result.notes:
        handoff_attributes["notes"] = ";".join(result.notes[:5])

    trace.emit(
        case_id=case_id,
        event_type="handoff",
        actor=ACTOR,
        target=TARGET_COORDINATOR,
        decision_code=f"entity_{status}",
        evidence_refs=result.evidence_refs or None,
        attributes=handoff_attributes,
    )
    return result
