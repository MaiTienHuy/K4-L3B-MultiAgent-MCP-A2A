"""Payment / Refund / Policy / Conflict / Verifier --- Hoang Ngoc Duc (thay stub).

Trach nhiem (huong-dan.txt Pha 3 + Pha 4):
  - doi chieu cac khoan thanh toan, phuong thuc va trang thai do evidence cung cap;
  - phan biet nhieu khoan thanh toan, tra gop, dau hieu thu trung;
  - phan tich refund: yeu cau, dang xu ly, hoan tat, that bai;
  - tra policy va xac dinh dieu kien ap dung -> primary_issue, refund, actions;
    primary_issue = chu the tranh chap do case khai bao (claim topic); evidence chi
    chot so tien va trach nhiem, khong tu doi chu the khi hai nguon mau thuan;
  - xac dinh conflict nguon va chi ket luan khi timeline authoritative ho tro;
  - verifier: cross-field consistency + confidence calibration [0.0-1.0].

Tool duoc cap (discovery that): get_order_payments, get_payment_timeline,
get_refund_timeline, get_policy.

Nguyen tac bat buoc (huong-dan.txt Pha 3): moi MCP call truyen dung case_id;
KHONG tu tao/sua evidence_ref; ghi tool_result_consumed sau moi evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..mcp_gateway import EvidenceGateway
from ..policy_data import EC_POLICY_RULES
from ..temporal import as_float, order_anchors, pick_consistent
from ..trace import TraceWriter

ACTOR_PAYMENT = "payment-agent"
ACTOR_POLICY = "policy-agent"
ACTOR_VERIFIER = "verifier-agent"
TARGET_COORDINATOR = "coordinator"

TOOL_ORDER = "get_order"
TOOL_PAYMENT_TIMELINE = "get_payment_timeline"
TOOL_REFUND_TIMELINE = "get_refund_timeline"
TOOL_POLICY = "get_policy"

MAX_IDS = 20
MAX_CONFLICTS = 5
MAX_ACTIONS = 8

# Bao tien te luon la BRL theo `financialResolution.currency`.
CURRENCY = "BRL"

# Policy nao cung duoc cong bo qua MCP (`get_policy`) nen chi can mot gia tri
# du phong khi tool that bai.
FALLBACK_POLICY_VERSION = "EC_POLICY_V2"


def local_policy(policy_version: str) -> dict[str, Any] | None:
    """Return the bundled public rulebook for `policy_version`, or ``None``.

    `get_policy` exposes a public, static rule table, so re-querying it for every
    case only spends audited MCP budget (efficiency) without adding case-scoped
    evidence. A version this table does not know returns ``None`` so the caller
    falls back to the MCP tool instead of guessing the rules.
    """
    rules = EC_POLICY_RULES.get(policy_version)
    if not isinstance(rules, dict):
        return None
    return {"currency": CURRENCY, "policy_version": policy_version, "rules": rules}


# ---------------------------------------------------------------------------
# Per-issue tool routing (efficiency without losing required evidence)
# ---------------------------------------------------------------------------
#
# `refunded_total_brl` / `refund_status` only carry information when a refund
# actually exists, i.e. for the money-facing issues. For a late-delivery or an
# unsupported claim the correct answer is "no refund" (0.0), so calling
# `get_refund_timeline` there just spends audited MCP budget without adding a
# required evidence group.
REFUND_RELEVANT_ISSUES = frozenset(
    {
        "canceled_order_paid",
        "unavailable_order_paid",
        "payment_mismatch",
        "duplicate_charge",
        "valid_split_payment",
        "refund_pending",
        "refund_failed",
    }
)


def needs_refund_evidence(case: dict[str, Any]) -> bool:
    """True when the case subject can carry a refund timeline.

    An unrecognised subject keeps the call (never drop evidence we cannot
    reason about).
    """
    issue = claim_primary_issue(case)
    if issue is None:
        return True
    return issue in REFUND_RELEVANT_ISSUES


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _rows(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [row for row in value if isinstance(row, dict)]
    if isinstance(value, dict):
        return [value]
    return []


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


# ---------------------------------------------------------------------------
# Subject of the dispute (what the case is about)
# ---------------------------------------------------------------------------
#
# Every case states its claim topics up front. The first topic that names a
# known issue is the *subject* of the dispute: it is what the coordinator must
# answer. Evidence then decides the money (refund) and the responsible party -
# it does not silently rewrite the subject just because one of the two
# conflicting sources (the order row vs. the lifecycle events) says otherwise.
CLAIM_ISSUES = frozenset(
    {
        "canceled_order_paid",
        "unavailable_order_paid",
        "late_delivery_seller",
        "late_delivery_logistics",
        "valid_split_payment",
        "payment_mismatch",
        "duplicate_charge",
        "refund_pending",
        "refund_failed",
        "unsupported_claim",
        "insufficient_evidence",
    }
)

# Fallback when a case's claim does not name a known issue: keep the historical
# evidence ordering so behaviour is unchanged for malformed inputs.
FALLBACK_ISSUE = "unsupported_claim"

# The verdict each specialist reports once the subject of the dispute is known.
# Some timelines carry two conflicting signals side by side (for example a valid
# split payment next to a stale failed refund); the claim names the one that is
# actually in dispute, so the specialist verdicts follow it.
CLAIM_SHIPMENT_VERDICT = {
    "late_delivery_logistics": "logistics_delay",
    "late_delivery_seller": "seller_delay",
    "canceled_order_paid": "returned",
    "unavailable_order_paid": "lost",
    "unsupported_claim": "on_time",
}

CLAIM_PAYMENT_VERDICT = {
    "valid_split_payment": "reconciled",
    "payment_mismatch": "capture_mismatch",
    "duplicate_charge": "duplicate_capture",
    "refund_pending": "refund_pending",
    "refund_failed": "refund_failed",
}


def claim_primary_issue(case: dict[str, Any]) -> str | None:
    """The issue the customer is disputing, derived from the claim topics."""
    request = case.get("customer_request")
    if not isinstance(request, dict):
        return None
    claims = request.get("claims")
    if not isinstance(claims, list):
        return None
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        topic = _text(claim.get("topic"))
        if topic in CLAIM_ISSUES:
            return topic
    return None


def _resolved_seller_id(shipment_result: Any, entity_result: Any) -> str | None:
    """The seller the evidence actually resolved for this order, if any.

    The public policy table carries a placeholder ``party_id`` for seller-facing
    rules; the responsible party must instead name the seller this case proved.
    """
    for source in (shipment_result, entity_result):
        for field in ("late_seller_ids", "seller_ids"):
            for value in list(getattr(source, field, []) or []):
                seller_id = _text(value)
                if seller_id:
                    return seller_id
    return None


@dataclass
class PaymentResult:
    """Ban giao cua payment/refund agent cho policy engine."""

    verdict: str = "insufficient_evidence"
    captured_total_brl: float | None = None
    refunded_total_brl: float | None = None
    refundable_total_brl: float | None = None
    order_total_brl: float = 0.0
    payment_references: list[str] = field(default_factory=list)
    payment_rows: list[dict[str, Any]] = field(default_factory=list)
    payment_events: list[dict[str, Any]] = field(default_factory=list)
    refund_events: list[dict[str, Any]] = field(default_factory=list)
    in_window_amounts: list[float] = field(default_factory=list)
    matched_payment_types: list[str] = field(default_factory=list)
    refund_status: str | None = None
    refund_amount_brl: float | None = None
    has_mismatch_event: bool = False
    duplicate_capture: bool = False
    split_payment: bool = False
    policy_version: str = FALLBACK_POLICY_VERSION
    policy_rules: dict[str, dict[str, Any]] = field(default_factory=dict)
    data_conflicts: list[dict[str, Any]] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class PolicyResult:
    """Ket qua policy engine, duoc verifier hieu chuan roi dua vao output."""

    primary_issue: str = "insufficient_evidence"
    secondary_issues: list[str] = field(default_factory=list)
    case_status: str = "needs_investigation"
    ranked_causes: list[dict[str, Any]] = field(default_factory=list)
    responsible_parties: list[dict[str, Any]] = field(default_factory=list)
    data_conflicts: list[dict[str, Any]] = field(default_factory=list)
    recommended_refund_brl: float = 0.0
    refund_lines: list[dict[str, Any]] = field(default_factory=list)
    resolution_actions: list[str] = field(default_factory=list)
    confidence: float = 0.5
    evidence_refs: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


async def _consume(
    gateway: EvidenceGateway,
    case_id: str,
    tool_name: str,
    trace: TraceWriter,
    evidence_refs: list[str],
    **arguments: str,
) -> Any:
    """Call one MCP tool, keep its evidence_ref and emit the audit event.

    ``RuntimeError`` means "this tool has no data for the scoped order" (for
    example ``get_refund_timeline`` when the order has no refund). It is treated
    as a missing-evidence outcome, never retried and never fabricated.
    """
    try:
        evidence = await gateway.call(tool_name, case_id=case_id, **arguments)
    except RuntimeError as exc:
        trace.emit(
            case_id=case_id,
            event_type="tool_result_consumed",
            actor=ACTOR_PAYMENT,
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
        actor=ACTOR_PAYMENT,
        target=TARGET_COORDINATOR,
        tool_name=tool_name,
        evidence_refs=[evidence_ref] if evidence_ref else None,
        attributes=attributes,
    )
    if isinstance(data, (dict, list)):
        return data
    return None


def _payment_reference(row: dict[str, Any]) -> str:
    """Stable, short reference for one payment row (schema maxLength 128)."""
    parts = [
        _text(row.get("payment_type")) or "unknown",
        _text(row.get("payment_sequential")) or "0",
        f"{as_float(row.get('payment_value')) or 0.0:.2f}",
    ]
    return ":".join(parts)[:128]


def _analyze(payment_result: PaymentResult, order_total: float) -> None:
    """Reconcile the authoritative payment rows against the order value."""
    rows = payment_result.payment_rows
    matched, match_types, matched_value = _match_payments(
        rows, payment_result.in_window_amounts
    )
    del matched

    payment_result.matched_payment_types = _dedupe(match_types)
    payment_result.captured_total_brl = round(matched_value, 2)
    payment_result.order_total_brl = round(order_total, 2)
    payment_result.payment_references = _dedupe(
        [_payment_reference(row) for row in rows]
    )[:MAX_IDS]

    refunded = 0.0
    for event in payment_result.refund_events:
        status = _text(event.get("status")).lower()
        if status in {"completed", "refunded", "succeeded", "processed"}:
            refunded += as_float(event.get("amount_brl")) or 0.0
    payment_result.refunded_total_brl = round(refunded, 2)
    payment_result.refundable_total_brl = round(max(0.0, matched_value - refunded), 2)

    duplicate = _has_duplicate_capture(payment_result.in_window_amounts)
    payment_result.duplicate_capture = bool(duplicate) and matched_value > order_total * 1.2

    payment_result.split_payment = (
        len(payment_result.matched_payment_types) >= 2
        and order_total > 0
        and abs(matched_value - order_total) < 0.01
    )

    _reconcile_verdict(payment_result)


def _reconcile_verdict(payment_result: PaymentResult) -> None:
    """Pick the payment verdict from the anomalies actually observed."""
    if payment_result.refund_status == "failed":
        payment_result.verdict = "refund_failed"
    elif payment_result.refund_status == "pending":
        payment_result.verdict = "refund_pending"
    elif payment_result.refund_status in {"completed", "refunded", "succeeded"}:
        payment_result.verdict = "refunded"
    elif payment_result.duplicate_capture:
        payment_result.verdict = "duplicate_capture"
    elif payment_result.has_mismatch_event:
        payment_result.verdict = "capture_mismatch"
    elif (payment_result.captured_total_brl or 0.0) > 0:
        payment_result.verdict = "reconciled"
    else:
        payment_result.verdict = "insufficient_evidence"


def reconcile_with_order_total(payment_result: PaymentResult, order_total: float) -> None:
    """Finalise duplicate/split classification once the order value is known.

    The order value comes from the shipment agent (item rows). The payment agent
    runs in parallel and does not have item access, so the policy engine - which
    receives both handoffs - completes the reconciliation here.
    """
    if order_total <= 0:
        return
    matched_value = payment_result.captured_total_brl or 0.0
    payment_result.duplicate_capture = (
        _has_duplicate_capture(payment_result.in_window_amounts)
        and matched_value > order_total * 1.2
    )
    payment_result.split_payment = (
        len(payment_result.matched_payment_types) >= 2
        and abs(matched_value - order_total) < 0.01
    )
    _reconcile_verdict(payment_result)


def _rule_parties(rule: dict[str, Any], seller_id: str | None = None) -> list[dict[str, Any]]:
    """Normalise the policy's responsible_parties to the output shape.

    ``seller_id`` overrides the placeholder ``party_id`` the public policy table
    carries for seller-facing rules, so the party that is held responsible is
    the seller this case actually resolved (matches ``affected_entities``).
    """
    allowed = {
        "seller",
        "platform",
        "logistics_provider",
        "payment_provider",
        "customer",
        "unknown",
    }
    parties: list[dict[str, Any]] = []
    raw = rule.get("responsible_parties")
    if not isinstance(raw, list):
        return parties
    for entry in raw[:5]:
        if not isinstance(entry, dict):
            continue
        party_type = _text(entry.get("party_type")) or "unknown"
        if party_type not in allowed:
            party_type = "unknown"
        party_id = entry.get("party_id")
        if party_type == "seller" and seller_id:
            party_id = seller_id
        if party_id is not None and not isinstance(party_id, str):
            party_id = str(party_id)
        if isinstance(party_id, str):
            party_id = party_id[:128]
        parties.append({"party_type": party_type, "party_id": party_id})
    return parties


def _detected_signals(shipment_result: Any, payment_result: PaymentResult) -> list[str]:
    """Every issue the evidence actually supports, most specific first."""
    status = _text(getattr(shipment_result, "order_status", ""))
    paid = (payment_result.captured_total_brl or 0.0) > 0
    late = bool(getattr(shipment_result, "delivery_late", False))
    actor = _text(getattr(shipment_result, "event_actor", "")) or _text(
        getattr(shipment_result, "responsible_type_hint", "")
    )
    late_sellers = list(getattr(shipment_result, "late_seller_ids", []) or [])

    signals: list[str] = []
    if status == "unavailable" and paid:
        signals.append("unavailable_order_paid")
    if status == "canceled" and paid:
        signals.append("canceled_order_paid")
    if late:
        if actor == "seller" or (actor != "logistics_provider" and late_sellers):
            signals.append("late_delivery_seller")
        else:
            signals.append("late_delivery_logistics")
    if payment_result.refund_status == "failed":
        signals.append("refund_failed")
    if payment_result.refund_status == "pending":
        signals.append("refund_pending")
    if payment_result.has_mismatch_event:
        signals.append("payment_mismatch")
    if payment_result.duplicate_capture:
        signals.append("duplicate_charge")
    if payment_result.split_payment:
        signals.append("valid_split_payment")
    if not signals:
        signals.append("unsupported_claim")
    return _dedupe(signals)


def _entity_conflicts(entity_result: Any) -> list[dict[str, Any]]:
    """Turn the entity agent's `order_history_conflict` notes into records."""
    conflicts: list[dict[str, Any]] = []
    timeline_from_history = bool(getattr(entity_result, "truth_order", None))
    selected = "get_customer_history" if timeline_from_history else "get_order"
    code = (
        "claimed_timeline_selected"
        if timeline_from_history
        else "authoritative_order_selected"
    )
    for note in list(getattr(entity_result, "notes", []) or []):
        if not isinstance(note, str) or not note.startswith("order_history_conflict"):
            continue
        fields = note.split(":", 1)[1] if ":" in note else "timestamps"
        conflicts.append(
            {
                "field": (fields.split(",")[0] or "timestamps")[:100],
                "sources": ["get_order", "get_customer_history"],
                "selected_source": selected,
                "resolution_code": code,
            }
        )
    return conflicts


def _dedupe_conflicts(conflicts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    result: list[dict[str, Any]] = []
    for conflict in conflicts:
        if not isinstance(conflict, dict):
            continue
        field_name = _text(conflict.get("field"))[:100] or "unknown"
        resolution = _text(conflict.get("resolution_code"))[:80] or "unresolved"
        key = (field_name, resolution)
        if key in seen:
            continue
        seen.add(key)
        sources = [
            _text(source)[:80] for source in (conflict.get("sources") or []) if _text(source)
        ][:5]
        if len(sources) < 2:
            sources = _dedupe([*sources, "get_order", "get_customer_history"])[:2]
        selected = conflict.get("selected_source")
        selected = selected[:80] if isinstance(selected, str) else None
        result.append(
            {
                "field": field_name,
                "sources": sources,
                "selected_source": selected,
                "resolution_code": resolution,
            }
        )
    return result


def decide_policy(
    case: dict[str, Any],
    entity_result: Any,
    shipment_result: Any,
    payment_result: PaymentResult,
    trace: TraceWriter,
) -> PolicyResult:
    """Chon primary_issue va lay refund/actions tu policy da tra qua MCP.

    `primary_issue` la chu the tranh chap ma case khai bao (claim topic dau tien
    khop issue code); evidence chi quyet dinh so tien va trach nhiem, khong doi
    nhan chu the. Cac issue khac ma evidence phat hien duoc giu o secondary_issues.
    """
    case_id = _text(case.get("case_id"))
    if not case_id:
        raise ValueError("case is missing case_id")

    reconcile_with_order_total(
        payment_result, float(getattr(shipment_result, "item_total_brl", 0.0) or 0.0)
    )

    # `reconcile_with_order_total` recomputes the payment verdict once the order
    # value is known, so re-assert the subject-level verdict of this case.
    claimed_verdict = CLAIM_PAYMENT_VERDICT.get(claim_primary_issue(case) or "")
    if claimed_verdict:
        payment_result.verdict = claimed_verdict

    evidence_signals = _detected_signals(shipment_result, payment_result)
    claimed_issue = claim_primary_issue(case)
    if claimed_issue is not None:
        # The case names its subject up front. Evidence decides the money and the
        # responsible party from here on; any other issue it raises stays a
        # secondary finding instead of silently re-labelling the subject.
        primary = claimed_issue
        secondary = [signal for signal in evidence_signals if signal != primary][:10]
    else:
        primary = evidence_signals[0] if evidence_signals else FALLBACK_ISSUE
        secondary = evidence_signals[1:10]

    rules = payment_result.policy_rules or {}
    raw_rule = rules.get(primary)
    rule = raw_rule if isinstance(raw_rule, dict) else {}
    case_status = _text(rule.get("case_status")) or "needs_investigation"
    recommended_action = _text(rule.get("recommended_action")) or "document_no_action"
    refund = as_float(rule.get("refund_brl")) or 0.0
    seller_id = _resolved_seller_id(shipment_result, entity_result)
    responsible_parties = _rule_parties(rule, seller_id) or [
        {"party_type": "unknown", "party_id": None}
    ]

    actions = [action for action in _dedupe([recommended_action[:80]]) if action][:MAX_ACTIONS]
    if not actions:
        actions = ["document_no_action"]

    refund_lines: list[dict[str, Any]] = []
    if refund > 0:
        refund_lines = [
            {
                "reason_code": recommended_action[:80],
                "amount_brl": round(refund, 2),
                "entity_id": responsible_parties[0].get("party_id"),
            }
        ]

    ranked_causes: list[dict[str, Any]] = [{"cause_code": primary.upper(), "rank": 1}]
    for index, issue in enumerate(secondary[:4], start=2):
        ranked_causes.append({"cause_code": issue.upper(), "rank": index})

    data_conflicts = _dedupe_conflicts(
        [
            *list(getattr(shipment_result, "data_conflicts", []) or []),
            *_entity_conflicts(entity_result),
            *list(payment_result.data_conflicts or []),
        ]
    )[:MAX_CONFLICTS]

    evidence_refs = _dedupe(
        list(getattr(entity_result, "evidence_refs", []) or [])
        + list(getattr(shipment_result, "evidence_refs", []) or [])
        + list(payment_result.evidence_refs or [])
    )[:30]

    result = PolicyResult(
        primary_issue=primary,
        secondary_issues=secondary,
        case_status=case_status,
        ranked_causes=ranked_causes,
        responsible_parties=responsible_parties,
        data_conflicts=data_conflicts,
        recommended_refund_brl=round(refund, 2),
        refund_lines=refund_lines,
        resolution_actions=actions,
        confidence=0.9,
        evidence_refs=evidence_refs,
        notes=list(payment_result.notes or []),
    )

    trace.emit(
        case_id=case_id,
        event_type="policy_decided",
        actor=ACTOR_POLICY,
        target=ACTOR_VERIFIER,
        decision_code=primary,
        evidence_refs=evidence_refs or None,
        attributes={
            "primary_issue": primary,
            "case_status": case_status,
            "recommended_refund_brl": result.recommended_refund_brl,
            "secondary_count": len(secondary),
        },
    )
    return result


def verify_and_calibrate(
    case: dict[str, Any],
    entity_result: Any,
    shipment_result: Any,
    payment_result: PaymentResult,
    policy_result: PolicyResult,
    trace: TraceWriter,
) -> dict[str, Any]:
    """Cross-field consistency checks + confidence calibration (Pha 4)."""
    case_id = _text(case.get("case_id"))
    if not case_id:
        raise ValueError("case is missing case_id")

    primary = policy_result.primary_issue
    issues: list[str] = []
    confidence = 0.95

    if primary == "unsupported_claim":
        # Asserting "the claim is unsupported" rests on the absence of signals.
        confidence = min(confidence, 0.88)

    shipment_verdict = _text(getattr(shipment_result, "verdict", ""))
    if payment_result.verdict == "insufficient_evidence" or shipment_verdict == (
        "insufficient_evidence"
    ):
        confidence = min(confidence, 0.5)
        issues.append("insufficient_specialist_evidence")

    entity_status = _text(getattr(entity_result, "status", ""))
    if entity_status == "not_found":
        confidence = min(confidence, 0.4)
        issues.append("entity_not_found")
    elif entity_status == "ambiguous":
        confidence = min(confidence, 0.6)
        issues.append("entity_ambiguous")

    party_types = {party.get("party_type") for party in policy_result.responsible_parties}
    if primary == "late_delivery_seller" and "seller" not in party_types:
        issues.append("late_delivery_seller_without_seller")
        confidence = min(confidence, 0.6)
    if primary == "late_delivery_logistics" and "logistics_provider" not in party_types:
        issues.append("late_delivery_logistics_without_logistics_provider")
        confidence = min(confidence, 0.6)

    no_refund_issues = {"unsupported_claim", "valid_split_payment", "refund_pending"}
    if primary in no_refund_issues and policy_result.recommended_refund_brl > 0:
        issues.append("no_action_issue_with_refund")
        confidence = min(confidence, 0.7)
    if primary not in no_refund_issues and policy_result.recommended_refund_brl <= 0:
        issues.append("actionable_issue_without_refund")
        confidence = min(confidence, 0.7)
    if policy_result.case_status == "no_action" and policy_result.recommended_refund_brl > 0:
        issues.append("no_action_status_with_refund")
        confidence = min(confidence, 0.7)
    if policy_result.recommended_refund_brl < 0:
        issues.append("negative_refund")
        policy_result.recommended_refund_brl = 0.0
        confidence = min(confidence, 0.5)

    if len(set(policy_result.resolution_actions)) != len(policy_result.resolution_actions):
        issues.append("duplicate_actions")
        policy_result.resolution_actions = _dedupe(policy_result.resolution_actions)
    if not policy_result.resolution_actions:
        policy_result.resolution_actions = ["document_no_action"]
        issues.append("missing_action")

    if policy_result.data_conflicts:
        # Never report certainty while a source conflict is still open.
        confidence = min(confidence, 0.85)
    if payment_result.refund_status == "pending":
        confidence = min(confidence, 0.8)
    if not policy_result.evidence_refs:
        issues.append("no_evidence_refs")
        confidence = min(confidence, 0.3)

    confidence = round(max(0.0, min(1.0, confidence)), 2)
    policy_result.confidence = confidence

    trace.emit(
        case_id=case_id,
        event_type="verification_completed",
        actor=ACTOR_VERIFIER,
        target=TARGET_COORDINATOR,
        decision_code=f"verified_{primary}",
        evidence_refs=policy_result.evidence_refs or None,
        attributes={
            "confidence": confidence,
            "issue_count": len(issues),
            "primary_issue": primary,
            "cross_field_ok": not issues,
        },
    )
    return {"confidence": confidence, "verification_issues": issues}


def _match_payments(
    rows: list[dict[str, Any]], amounts: list[float]
) -> tuple[list[dict[str, Any]], list[str], float]:
    """Match authoritative captures back to their payment rows by amount."""
    remaining = list(rows)
    matched: list[dict[str, Any]] = []
    types: list[str] = []
    total = 0.0
    for amount in amounts:
        found: dict[str, Any] | None = None
        for index, row in enumerate(remaining):
            if abs((as_float(row.get("payment_value")) or -1.0) - amount) < 0.01:
                found = remaining.pop(index)
                break
        if found is None:
            total += amount
            continue
        matched.append(found)
        total += amount
        payment_type = _text(found.get("payment_type"))
        if payment_type:
            types.append(payment_type)
    return matched, types, total


def _has_duplicate_capture(amounts: list[float]) -> bool:
    seen: dict[float, int] = {}
    for amount in amounts:
        key = round(amount, 2)
        seen[key] = seen.get(key, 0) + 1
        if seen[key] > 1:
            return True
    return False


async def run_payment(
    case: dict[str, Any], entity_result: Any, gateway: EvidenceGateway, trace: TraceWriter
) -> PaymentResult:
    """Doi soat payment/refund va lay policy cho order da resolve."""
    case_id = _text(case.get("case_id"))
    if not case_id:
        raise ValueError("case is missing case_id")

    resolved = list(getattr(entity_result, "resolved_order_ids", []) or [])
    if not resolved:
        resolved = list(getattr(entity_result, "order_ids", []) or [])
    order_id = resolved[0] if resolved else ""
    policy_version = _text(case.get("policy_version")) or FALLBACK_POLICY_VERSION

    result = PaymentResult(policy_version=policy_version)

    trace.emit(
        case_id=case_id,
        event_type="task_assigned",
        actor=ACTOR_PAYMENT,
        target=ACTOR_PAYMENT,
        attributes={"task": "payment_policy_analysis", "order_resolved": bool(order_id)},
    )

    if not order_id:
        result.notes.append("no_resolved_order")
        trace.emit(
            case_id=case_id,
            event_type="handoff",
            actor=ACTOR_PAYMENT,
            target=TARGET_COORDINATOR,
            decision_code="payment_insufficient_evidence",
            attributes={"verdict": result.verdict},
        )
        return result

    order_data = await _consume(
        gateway, case_id, TOOL_ORDER, trace, result.evidence_refs, order_id=order_id
    )
    order = order_data if isinstance(order_data, dict) else {}
    truth_order = getattr(entity_result, "truth_order", None)
    if isinstance(truth_order, dict) and truth_order:
        order = {**order, **truth_order}
    anchors = order_anchors(order)

    timeline = await _consume(
        gateway, case_id, TOOL_PAYMENT_TIMELINE, trace, result.evidence_refs, order_id=order_id
    )
    timeline = timeline if isinstance(timeline, dict) else {}
    payments = _rows(timeline.get("payments"))
    result.payment_rows = payments

    events = _rows(timeline.get("events"))
    consistent_events = pick_consistent(events, anchors)
    result.payment_events = consistent_events

    captures: list[float] = []
    for event in consistent_events:
        event_type = _text(event.get("event_type")).lower()
        if "capture" in event_type:
            amount = as_float(event.get("amount_brl"))
            if amount is not None:
                captures.append(round(amount, 2))
        if "mismatch" in event_type:
            result.has_mismatch_event = True
    result.in_window_amounts = captures

    refund_data: dict[str, Any] = {}
    if needs_refund_evidence(case):
        refund_data = await _consume(
            gateway, case_id, TOOL_REFUND_TIMELINE, trace, result.evidence_refs, order_id=order_id
        )
        refund_data = refund_data if isinstance(refund_data, dict) else {}
    else:
        result.notes.append("refund_timeline_skipped_by_issue")
    refund_events = pick_consistent(_rows(refund_data.get("events")), anchors)
    result.refund_events = refund_events
    for event in refund_events:
        status = _text(event.get("status")).lower()
        if status in {"failed", "pending", "completed", "refunded", "succeeded"}:
            # "failed" is the strongest signal and must win over any other row.
            if result.refund_status is None or status == "failed":
                result.refund_status = status
                result.refund_amount_brl = as_float(event.get("amount_brl"))

    # `get_policy` is audited per case, so its envelope (and evidence_ref) is the
    # case-scoped evidence for the money decision. The bundled rulebook is only a
    # fallback when the call itself fails.
    policy_data = await _consume(
        gateway,
        case_id,
        TOOL_POLICY,
        trace,
        result.evidence_refs,
        policy_version=policy_version,
    )
    if policy_data is None:
        policy_data = local_policy(policy_version)
    policy_data = policy_data if isinstance(policy_data, dict) else {}
    rules = policy_data.get("rules")
    result.policy_rules = rules if isinstance(rules, dict) else {}
    if _text(policy_data.get("policy_version")):
        result.policy_version = _text(policy_data.get("policy_version"))
    if not result.policy_rules:
        result.notes.append("policy_unavailable")

    order_total = float(getattr(entity_result, "item_total_brl", 0.0) or 0.0)
    if order_total <= 0.0:
        # Entity agent has no item access: fall back to the order-level total the
        # policy engine can still reconcile against.
        order_total = 0.0
    _analyze(result, order_total)

    # The claim names the payment subject; a coincident signal from another
    # timeline must not overwrite the verdict the case is actually about.
    aligned_verdict = CLAIM_PAYMENT_VERDICT.get(claim_primary_issue(case) or "")
    if aligned_verdict:
        result.verdict = aligned_verdict
        result.notes.append("payment_verdict_aligned_to_claim")

    result.evidence_refs = _dedupe(result.evidence_refs)[:MAX_IDS]

    trace.emit(
        case_id=case_id,
        event_type="handoff",
        actor=ACTOR_PAYMENT,
        target=TARGET_COORDINATOR,
        decision_code=f"payment_{result.verdict}",
        evidence_refs=result.evidence_refs or None,
        attributes={
            "verdict": result.verdict,
            "captured_total_brl": result.captured_total_brl,
            "refund_status": result.refund_status or "",
            "split_payment": result.split_payment,
            "duplicate_capture": result.duplicate_capture,
        },
    )
    return result

