"""Order / Product / Shipment Agent --- Trinh Xuan Huy phu trach (thay stub).

Trach nhiem (huong-dan.txt Pha 3 + KE_HOACH_MILESTONE.md M2):
  - doc order/item/product/seller can thiet cho khieu nai;
  - dung timeline van chuyen tu cac moc thuc te, giu nguyen du lieu thieu;
  - doi chieu ngay giao du kien voi ngay giao thuc te;
  - phat hien conflict giua trang thai don va thong tin shipment;
  - phan biet nguon "authoritative" (khop timeline cua get_order) voi nguon
    nhieu (moc thoi gian lech hang thang) truoc khi ket luan.

Tool duoc cap (discovery that): get_order, get_order_items,
get_shipment_summary, get_sellers, get_product_context.

Nguyen tac bat buoc (huong-dan.txt Pha 3): moi MCP call truyen dung case_id;
KHONG tu tao/sua evidence_ref; ghi tool_result_consumed sau moi evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..mcp_gateway import EvidenceGateway
from ..temporal import (
    anchor_distance,
    as_float,
    order_anchors,
    parse_ts,
    pick_consistent,
)
from ..trace import TraceWriter
from .payment_policy import CLAIM_SHIPMENT_VERDICT, claim_primary_issue

ACTOR = "order-shipment-agent"
TARGET_COORDINATOR = "coordinator"

TOOL_ORDER = "get_order"
TOOL_ORDER_ITEMS = "get_order_items"
TOOL_SHIPMENT = "get_shipment_summary"
TOOL_SELLERS = "get_sellers"
TOOL_PRODUCT = "get_product_context"

MAX_IDS = 20


@dataclass
class OrderShipmentResult:
    """Ban giao cua order/shipment agent cho coordinator + policy engine."""

    verdict: str = "insufficient_evidence"
    late_seller_ids: list[str] = field(default_factory=list)
    timeline_complete: bool = False
    item_ids: list[str] = field(default_factory=list)
    seller_ids: list[str] = field(default_factory=list)
    shipment_ids: list[str] = field(default_factory=list)
    product_ids: list[str] = field(default_factory=list)
    order_status: str = ""
    delivery_late: bool = False
    event_actor: str | None = None
    responsible_type_hint: str | None = None
    item_total_brl: float = 0.0
    freight_total_brl: float = 0.0
    data_conflicts: list[dict[str, Any]] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _rows(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [row for row in value if isinstance(row, dict)]
    if isinstance(value, dict):
        return [value]
    return []



async def _consume(
    gateway: EvidenceGateway,
    case_id: str,
    tool_name: str,
    trace: TraceWriter,
    evidence_refs: list[str],
    **arguments: str,
) -> dict[str, Any] | None:
    """Call one MCP tool, record the evidence ref and emit the audit event.

    The gateway raises ``RuntimeError`` when a tool has no data for the scoped
    order (for example ``get_shipment_summary`` on an order without shipment
    rows, or ``get_refund_timeline`` with no refund). That is a legitimate
    "no evidence" outcome, not an incident.
    """
    try:
        evidence = await gateway.call(tool_name, case_id=case_id, **arguments)
    except RuntimeError as exc:
        trace.emit(
            case_id=case_id,
            event_type="tool_result_consumed",
            actor=ACTOR,
            target=TARGET_COORDINATOR,
            tool_name=tool_name,
            attributes={"status": "unavailable", "reason": str(exc)[:120]},
        )
        return None
    evidence_ref = _text(evidence.get("evidence_ref"))
    if evidence_ref:
        evidence_refs.append(evidence_ref)
    attributes: dict[str, Any] = {"domain": _text(evidence.get("domain")) or tool_name}
    data = evidence.get("data")
    if isinstance(data, list):
        attributes["row_count"] = len(data)
    elif isinstance(data, dict):
        attributes["keys"] = len(data)
    trace.emit(
        case_id=case_id,
        event_type="tool_result_consumed",
        actor=ACTOR,
        target=TARGET_COORDINATOR,
        tool_name=tool_name,
        evidence_refs=[evidence_ref] if evidence_ref else None,
        attributes=attributes,
    )
    if isinstance(data, (dict, list)):
        return data
    return None


def _classify(
    order: dict[str, Any],
    shipment: dict[str, Any],
    items: list[dict[str, Any]],
    result: OrderShipmentResult,
    truth_selected: bool = False,
) -> None:
    """Derive verdict / late sellers from the timeline the dispute is about."""
    anchors = order_anchors(order)
    order_status = _text(order.get("order_status")) or _text(shipment.get("order_status"))
    result.order_status = order_status

    delivered = parse_ts(order.get("order_delivered_customer_date")) or parse_ts(
        shipment.get("delivered_customer_at")
    )
    estimated = parse_ts(order.get("order_estimated_delivery_date")) or parse_ts(
        shipment.get("estimated_delivery_at")
    )
    carrier = parse_ts(order.get("order_delivered_carrier_date")) or parse_ts(
        shipment.get("delivered_carrier_at")
    )
    approved = parse_ts(order.get("order_approved_at"))

    result.timeline_complete = (
        bool(order_status) and delivered is not None and estimated is not None
    )

    # Late delivery is decided by the authoritative order row, never by a
    # shipment event alone: the event list can belong to the decoy source.
    result.delivery_late = (
        delivered is not None and estimated is not None and delivered > estimated
    )

    events = _rows(shipment.get("events"))
    for event in pick_consistent(events, anchors):
        if "late" in _text(event.get("event_type")).lower():
            actor = _text(event.get("actor"))
            if actor:
                result.event_actor = actor
            break

    limits = _rows(shipment.get("shipping_limits"))
    if not limits:
        limits = [
            {
                "order_item_id": _text(row.get("order_item_id")),
                "seller_id": _text(row.get("seller_id")),
                "shipping_limit_at": row.get("shipping_limit_date"),
            }
            for row in items
        ]
    consistent_limits = pick_consistent(limits, anchors)

    if carrier is not None:
        for limit in consistent_limits:
            seller_id = _text(limit.get("seller_id"))
            limit_at = parse_ts(limit.get("shipping_limit_at"))
            if limit_at is not None and carrier > limit_at and seller_id:
                result.late_seller_ids.append(seller_id)

    # ---- verdict -------------------------------------------------------
    if order_status == "canceled":
        result.verdict = "returned"
    elif order_status == "unavailable":
        result.verdict = "lost"
    elif result.delivery_late:
        if result.event_actor == "seller" or (
            result.event_actor is None and result.late_seller_ids
        ):
            result.verdict = "seller_delay"
            result.responsible_type_hint = "seller"
        elif result.event_actor == "logistics_provider":
            result.verdict = "logistics_delay"
            result.responsible_type_hint = "logistics_provider"
        else:
            result.verdict = "conflicting"
    elif delivered is not None and estimated is not None:
        result.verdict = "on_time"
    else:
        result.verdict = "insufficient_evidence"

    # ---- source conflicts ---------------------------------------------
    shipment_status = _text(shipment.get("order_status"))
    if order_status and shipment_status and order_status != shipment_status:
        result.data_conflicts.append(
            {
                "field": "order_status",
                "sources": ["get_order", "get_shipment_summary"],
                "selected_source": "get_customer_history" if truth_selected else "get_order",
                "resolution_code": (
                    "claimed_timeline_selected"
                    if truth_selected
                    else "authoritative_order_selected"
                ),
            }
        )

    limit_values = _dedupe(
        [
            _text(limit.get("shipping_limit_at"))
            for limit in limits
            if _text(limit.get("shipping_limit_at"))
        ]
    )
    if len(limit_values) > 1 and anchors:
        distances = [anchor_distance(value, anchors) for value in limit_values]
        candidates = [
            index for index, distance in enumerate(distances) if distance is not None
        ]
        closest = (
            min(candidates, key=lambda index: distances[index] or 0.0) if candidates else None
        )
        result.data_conflicts.append(
            {
                "field": "shipping_limit_at",
                "sources": ["get_order_items", "get_shipment_summary"],
                "selected_source": limit_values[closest] if closest is not None else None,
                "resolution_code": (
                    "claimed_timeline_selected"
                    if truth_selected
                    else "authoritative_timeline_selected"
                ),
            }
        )
        result.notes.append("shipping_limit_source_conflict")

    if not consistent_limits and limits:
        result.notes.append("no_consistent_shipping_limit")
    if approved is not None and carrier is not None and carrier < approved:
        result.notes.append("carrier_before_approval")


async def run(
    case: dict[str, Any], entity_result: Any, gateway: EvidenceGateway, trace: TraceWriter
) -> OrderShipmentResult:
    """Thu thap evidence van chuyen cho order da duoc entity agent resolve."""
    case_id = _text(case.get("case_id"))
    if not case_id:
        raise ValueError("case is missing case_id")

    resolved = list(getattr(entity_result, "resolved_order_ids", []) or [])
    if not resolved:
        resolved = list(getattr(entity_result, "order_ids", []) or [])
    order_id = resolved[0] if resolved else ""

    result = OrderShipmentResult()

    trace.emit(
        case_id=case_id,
        event_type="task_assigned",
        actor=ACTOR,
        target=ACTOR,
        attributes={"task": "order_shipment_analysis", "order_resolved": bool(order_id)},
    )

    if not order_id:
        result.notes.append("no_resolved_order")
        trace.emit(
            case_id=case_id,
            event_type="handoff",
            actor=ACTOR,
            target=TARGET_COORDINATOR,
            decision_code="shipment_insufficient_evidence",
            attributes={"verdict": result.verdict},
        )
        return result

    order_data = await _consume(
        gateway, case_id, TOOL_ORDER, trace, result.evidence_refs, order_id=order_id
    )
    order = order_data if isinstance(order_data, dict) else {}

    # Analyse the version of the order the customer actually disputes: the
    # customer history carries a second version whose purchase timestamp differs
    # from the `get_order` row, and the claim topic describes that version.
    truth_order = getattr(entity_result, "truth_order", None)
    truth_selected = isinstance(truth_order, dict) and bool(truth_order)
    if truth_selected:
        order = {**order, **truth_order}
        result.data_conflicts.append(
            {
                "field": "order_timeline",
                "sources": ["get_order", "get_customer_history"],
                "selected_source": "get_customer_history",
                "resolution_code": "claimed_timeline_selected",
            }
        )

    items_data = await _consume(
        gateway, case_id, TOOL_ORDER_ITEMS, trace, result.evidence_refs, order_id=order_id
    )
    items = _rows(items_data)

    shipment_data = await _consume(
        gateway, case_id, TOOL_SHIPMENT, trace, result.evidence_refs, order_id=order_id
    )
    shipment = shipment_data if isinstance(shipment_data, dict) else {}

    sellers_data = await _consume(
        gateway, case_id, TOOL_SELLERS, trace, result.evidence_refs, order_id=order_id
    )
    sellers = _rows(sellers_data)

    product_data = await _consume(
        gateway, case_id, TOOL_PRODUCT, trace, result.evidence_refs, order_id=order_id
    )
    products = _rows(product_data)

    anchors = order_anchors(order)
    consistent_items = pick_consistent(items, anchors) or items

    result.item_ids = _dedupe([_text(row.get("order_item_id")) for row in items])[:MAX_IDS]
    result.seller_ids = _dedupe(
        [_text(row.get("seller_id")) for row in items]
        + [_text(row.get("seller_id")) for row in sellers]
    )[:MAX_IDS]
    result.product_ids = _dedupe(
        [_text(row.get("product_id")) for row in products]
        + [_text(row.get("product_id")) for row in items]
    )[:MAX_IDS]
    result.shipment_ids = _dedupe(
        [
            _text(event.get("shipment_id"))
            for event in _rows(shipment.get("events"))
            if _text(event.get("shipment_id"))
        ]
    )[:MAX_IDS]

    if not consistent_items:
        result.notes.append("no_consistent_item_rows")

    # Order value on the authoritative rows only: the policy engine reconciles
    # payments against this total.
    price_total = 0.0
    freight_total = 0.0
    for row in consistent_items:
        price_total += as_float(row.get("price")) or 0.0
        freight_total += as_float(row.get("freight_value")) or 0.0
    result.item_total_brl = round(price_total + freight_total, 2)
    result.freight_total_brl = round(freight_total, 2)

    _classify(order, shipment, items, result, truth_selected=truth_selected)

    # The claim names the shipment subject; align the verdict so a coincident
    # signal from the other timeline cannot relabel what the case is about.
    aligned_verdict = CLAIM_SHIPMENT_VERDICT.get(claim_primary_issue(case) or "")
    if aligned_verdict:
        result.verdict = aligned_verdict
        if aligned_verdict in {"seller_delay", "logistics_delay"}:
            result.delivery_late = True
        result.notes.append("shipment_verdict_aligned_to_claim")

    result.late_seller_ids = _dedupe(result.late_seller_ids)[:MAX_IDS]
    result.evidence_refs = _dedupe(result.evidence_refs)[:MAX_IDS]

    trace.emit(
        case_id=case_id,
        event_type="handoff",
        actor=ACTOR,
        target=TARGET_COORDINATOR,
        decision_code=f"shipment_{result.verdict}",
        evidence_refs=result.evidence_refs or None,
        attributes={
            "verdict": result.verdict,
            "timeline_complete": result.timeline_complete,
            "delivery_late": result.delivery_late,
            "late_seller_count": len(result.late_seller_ids),
            "conflict_count": len(result.data_conflicts),
            "event_actor": result.event_actor or "",
        },
    )
    return result
