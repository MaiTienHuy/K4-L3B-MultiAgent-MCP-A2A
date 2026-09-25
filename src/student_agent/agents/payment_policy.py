"""Payment, Refund, Policy & Verifier Agent --- Hoang Ngoc Duc phu trach (ho tro chay end-to-end de dong goi submission.zip)."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from ..trace import TraceWriter

PAYMENT_ACTOR = "payment-agent"
POLICY_ACTOR = "policy-agent"
VERIFIER_ACTOR = "verifier-agent"


def _unique_preserve_order(items: list[str], max_items: int = 20) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if isinstance(item, str) and item and item not in seen:
            seen.add(item)
            result.append(item)
            if len(result) >= max_items:
                break
    return result


@dataclass
class PaymentResult:
    verdict: str = "insufficient_evidence"
    captured_total_brl: float | None = None
    refunded_total_brl: float | None = None
    refundable_total_brl: float | None = None
    payments: list[dict[str, Any]] = field(default_factory=list)
    payment_events: list[dict[str, Any]] = field(default_factory=list)
    refund_events: list[dict[str, Any]] = field(default_factory=list)
    policy_rules: dict[str, Any] = field(default_factory=dict)
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)


@dataclass
class PolicyResult:
    primary_issue: str = "insufficient_evidence"
    secondary_issues: list[str] = field(default_factory=list)
    case_status: str = "needs_investigation"
    ranked_causes: list[dict[str, Any]] = field(default_factory=list)
    responsible_parties: list[dict[str, Any]] = field(default_factory=list)
    recommended_refund_brl: float = 0.0
    refund_lines: list[dict[str, Any]] = field(default_factory=list)
    resolution_actions: list[str] = field(default_factory=list)
    data_conflicts: list[dict[str, Any]] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    confidence: float = 0.85


async def run_payment(
    case: dict[str, Any],
    entity_result: Any,
    gateway: Any,
    trace: TraceWriter,
) -> PaymentResult:
    case_id = str(case["case_id"])
    trace.emit(
        case_id=case_id,
        event_type="task_assigned",
        actor="coordinator",
        target=PAYMENT_ACTOR,
    )

    order_ids = list(getattr(entity_result, "resolved_order_ids", []) or [])
    evidence_refs: list[str] = []
    all_payments: list[dict[str, Any]] = []
    payment_events: list[dict[str, Any]] = []
    refund_events: list[dict[str, Any]] = []
    payment_refs: list[str] = []
    conflicts: list[dict[str, Any]] = []
    policy_rules: dict[str, Any] = {}

    claims = (
        case.get("customer_request", {}).get("claims", [])
        if isinstance(case.get("customer_request"), dict)
        else []
    )
    claim_topics = {str(c.get("topic") or "") for c in claims if isinstance(c, dict)}
    need_refund_timeline = bool(claim_topics & {"refund_pending", "refund_failed"})

    async def _safe_call(t_name: str, **kwargs: str) -> tuple[str, dict[str, Any] | None]:
        try:
            res_ev = await gateway.call(t_name, case_id=case_id, **kwargs)
            return t_name, res_ev if isinstance(res_ev, dict) else None
        except Exception:
            return t_name, None

    policy_version = str(case.get("policy_version") or "EC_POLICY_V2")
    call_coros = [_safe_call("get_policy", policy_version=policy_version)]
    for oid in order_ids:
        call_coros.append(_safe_call("get_order_payments", order_id=oid))
        call_coros.append(_safe_call("get_payment_timeline", order_id=oid))
        if need_refund_timeline:
            call_coros.append(_safe_call("get_refund_timeline", order_id=oid))

    batch_results = await asyncio.gather(*call_coros)

    for tool_name, ev in batch_results:
        if not ev or not ev.get("evidence_ref"):
            continue
        ev_ref = str(ev["evidence_ref"])
        evidence_refs.append(ev_ref)
        trace.emit(
            case_id=case_id,
            event_type="tool_result_consumed",
            actor=POLICY_ACTOR if tool_name == "get_policy" else PAYMENT_ACTOR,
            tool_name=tool_name,
            evidence_refs=[ev_ref],
        )
        data = ev.get("data")
        if tool_name == "get_policy":
            if isinstance(data, dict) and isinstance(data.get("rules"), dict):
                policy_rules = data["rules"]
        elif tool_name == "get_order_payments" and isinstance(data, list):
            all_payments.extend(r for r in data if isinstance(r, dict))
        elif tool_name == "get_payment_timeline" and isinstance(data, dict):
            if isinstance(data.get("events"), list):
                payment_events.extend(r for r in data["events"] if isinstance(r, dict))
            if isinstance(data.get("payments"), list) and not all_payments:
                all_payments.extend(r for r in data["payments"] if isinstance(r, dict))
        elif tool_name == "get_refund_timeline":
            if isinstance(data, dict) and isinstance(data.get("events"), list):
                refund_events.extend(r for r in data["events"] if isinstance(r, dict))
            elif isinstance(data, list):
                refund_events.extend(r for r in data if isinstance(r, dict))

    if not order_ids:
        res = PaymentResult(policy_rules=policy_rules, evidence_refs=evidence_refs)
        trace.emit(
            case_id=case_id,
            event_type="handoff",
            actor=PAYMENT_ACTOR,
            target=POLICY_ACTOR,
            decision_code="insufficient_evidence",
        )
        return res

    for idx, p in enumerate(all_payments, 1):
        ref = (
            p.get("payment_reference")
            or p.get("payment_id")
            or f"pay-{p.get('order_id', 'ord')}-{p.get('payment_sequential', idx)}"
        )
        payment_refs.append(str(ref))
    if hasattr(entity_result, "payment_references"):
        entity_result.payment_references = _unique_preserve_order(payment_refs)

    # Calculate captured & refunded totals
    # Filter payment events by the primary order purchase date if duplicate historical rows exist
    order_purchase_ts: str | None = None
    if hasattr(entity_result, "orders_data") and order_ids:
        order_purchase_ts = (
            entity_result.orders_data.get(order_ids[0], {}).get("order_purchase_timestamp")
        )
    purchase_date_prefix = order_purchase_ts[:10] if isinstance(order_purchase_ts, str) else None

    captured_total = 0.0
    matched_events = [
        pev
        for pev in payment_events
        if purchase_date_prefix and str(pev.get("event_at") or "").startswith(purchase_date_prefix)
    ]
    active_payment_events = matched_events if matched_events else payment_events

    if active_payment_events:
        for pev in active_payment_events:
            if str(pev.get("status", "confirmed")) == "confirmed" and "capture" in str(
                pev.get("event_type", "")
            ).lower():
                try:
                    captured_total += float(pev.get("amount_brl") or 0.0)
                except (TypeError, ValueError):
                    pass
    if captured_total == 0.0 and all_payments:
        try:
            captured_total = float(all_payments[0].get("payment_value") or 0.0)
        except (TypeError, ValueError):
            pass

    refunded_total = 0.0
    has_refund_pending = False
    has_refund_failed = False
    has_duplicate_capture = False
    has_capture_mismatch = False

    for pev in payment_events:
        et = str(pev.get("event_type", "")).lower()
        if "duplicate" in et:
            has_duplicate_capture = True
        if "mismatch" in et:
            has_capture_mismatch = True
            conflicts.append(
                {
                    "field": "payment_value",
                    "sources": ["payment", "order"],
                    "selected_source": "payment",
                    "resolution_code": "AUTHORITATIVE_PAYMENT_TIMELINE",
                }
            )

    for rev in refund_events:
        et = str(rev.get("event_type") or rev.get("status") or "").lower()
        st = str(rev.get("status") or "").lower()
        amt = 0.0
        try:
            amt = float(rev.get("amount_brl") or rev.get("refund_amount_brl") or 0.0)
        except (TypeError, ValueError):
            pass
        if "fail" in et or "fail" in st:
            has_refund_failed = True
        elif "pend" in et or "pend" in st or "request" in et:
            has_refund_pending = True
        elif "refund" in et or "complete" in st or "confirm" in st:
            refunded_total += amt

    captured_total = round(captured_total, 2)
    refunded_total = round(refunded_total, 2)
    refundable_total = round(max(0.0, captured_total - refunded_total), 2)

    if has_refund_failed:
        verdict = "refund_failed"
    elif has_refund_pending:
        verdict = "refund_pending"
    elif refunded_total > 0:
        verdict = "refunded"
    elif has_duplicate_capture:
        verdict = "duplicate_capture"
    elif has_capture_mismatch:
        verdict = "capture_mismatch"
    elif captured_total > 0:
        verdict = "reconciled"
    else:
        verdict = "insufficient_evidence"

    res = PaymentResult(
        verdict=verdict,
        captured_total_brl=captured_total if captured_total > 0 else 0.0,
        refunded_total_brl=refunded_total,
        refundable_total_brl=refundable_total,
        payments=all_payments,
        payment_events=payment_events,
        refund_events=refund_events,
        policy_rules=policy_rules,
        conflicts=conflicts,
        evidence_refs=_unique_preserve_order(evidence_refs, max_items=30),
    )

    trace.emit(
        case_id=case_id,
        event_type="handoff",
        actor=PAYMENT_ACTOR,
        target=POLICY_ACTOR,
        decision_code=verdict,
        evidence_refs=res.evidence_refs[:20] or None,
    )
    return res


def decide_policy(
    case: dict[str, Any],
    entity_result: Any,
    shipment_result: Any,
    payment_result: PaymentResult,
    trace: TraceWriter,
) -> PolicyResult:
    case_id = str(case["case_id"])
    claims = (
        case.get("customer_request", {}).get("claims", [])
        if isinstance(case.get("customer_request"), dict)
        else []
    )
    claim_topics = [str(c.get("topic") or "") for c in claims if isinstance(c, dict)]

    ship_verdict = getattr(shipment_result, "verdict", "insufficient_evidence")
    pay_verdict = getattr(payment_result, "verdict", "insufficient_evidence")
    order_status = (
        shipment_result.delivery_status.get("order_status_summary", "unknown")
        if hasattr(shipment_result, "delivery_status")
        else "unknown"
    )

    valid_issues = {
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
    }

    primary_issue = "insufficient_evidence"
    if getattr(entity_result, "status", "not_found") == "not_found":
        primary_issue = "insufficient_evidence"
    elif order_status == "canceled" and (payment_result.captured_total_brl or 0) > 0:
        primary_issue = "canceled_order_paid"
    elif order_status == "unavailable" and (payment_result.captured_total_brl or 0) > 0:
        primary_issue = "unavailable_order_paid"
    elif pay_verdict == "refund_failed":
        primary_issue = "refund_failed"
    elif pay_verdict == "refund_pending":
        primary_issue = "refund_pending"
    elif pay_verdict == "duplicate_capture":
        primary_issue = "duplicate_charge"
    elif pay_verdict == "capture_mismatch":
        primary_issue = "payment_mismatch"
    elif ship_verdict == "seller_delay":
        primary_issue = "late_delivery_seller"
    elif ship_verdict == "logistics_delay":
        primary_issue = "late_delivery_logistics"
    else:
        for topic in claim_topics:
            if topic in valid_issues:
                primary_issue = topic
                break
        if primary_issue == "insufficient_evidence" and ship_verdict == "on_time":
            primary_issue = "unsupported_claim"

    rule = payment_result.policy_rules.get(primary_issue, {})
    case_status = str(
        rule.get("case_status")
        or (
            "action_required"
            if primary_issue
            not in (
                "valid_split_payment",
                "unsupported_claim",
                "insufficient_evidence",
                "refund_pending",
            )
            else (
                "no_action"
                if primary_issue in ("valid_split_payment", "unsupported_claim")
                else "needs_investigation"
            )
        )
    )
    recommended_refund = float(rule.get("refund_brl") or 0.0)
    action = str(
        rule.get("recommended_action")
        or ("document_no_action" if case_status == "no_action" else "investigate_case")
    )
    resp_parties = list(
        rule.get("responsible_parties") or [{"party_type": "unknown", "party_id": None}]
    )

    if primary_issue in ("late_delivery_seller", "unavailable_order_paid"):
        seller_ids = getattr(shipment_result, "late_seller_ids", []) or getattr(
            shipment_result, "seller_ids", []
        )
        if (
            seller_ids
            and resp_parties
            and resp_parties[0].get("party_type") == "seller"
            and not resp_parties[0].get("party_id")
        ):
            resp_parties = [{"party_type": "seller", "party_id": seller_ids[0]}]

    cause_code = primary_issue.upper()
    ranked_causes = [{"cause_code": cause_code, "rank": 1}]

    order_ids = getattr(entity_result, "resolved_order_ids", [])
    primary_oid = order_ids[0] if order_ids else None
    refund_lines = (
        [
            {
                "reason_code": primary_issue,
                "amount_brl": round(recommended_refund, 2),
                "entity_id": primary_oid,
            }
        ]
        if recommended_refund > 0
        else []
    )

    merged_conflicts = (
        list(getattr(shipment_result, "conflicts", []) or [])
        + list(getattr(payment_result, "conflicts", []) or [])
    )[:5]

    res = PolicyResult(
        primary_issue=primary_issue,
        secondary_issues=[],
        case_status=case_status,
        ranked_causes=ranked_causes,
        responsible_parties=resp_parties,
        recommended_refund_brl=round(recommended_refund, 2),
        refund_lines=refund_lines,
        resolution_actions=[action],
        data_conflicts=merged_conflicts,
        evidence_refs=[],
        confidence=0.88,
    )

    trace.emit(
        case_id=case_id,
        event_type="policy_decided",
        actor=POLICY_ACTOR,
        decision_code=primary_issue,
    )
    return res


def verify_and_calibrate(
    case: dict[str, Any],
    entity_result: Any,
    shipment_result: Any,
    payment_result: PaymentResult,
    policy_result: PolicyResult,
    trace: TraceWriter,
) -> dict[str, Any]:
    case_id = str(case["case_id"])
    conf = 0.90
    if getattr(entity_result, "status", "") == "not_found":
        conf = 0.35
    elif getattr(entity_result, "ambiguous", False):
        conf = 0.55
    elif policy_result.data_conflicts:
        conf = 0.85

    policy_result.confidence = round(conf, 2)
    trace.emit(
        case_id=case_id,
        event_type="verification_completed",
        actor=VERIFIER_ACTOR,
        decision_code=policy_result.primary_issue,
        attributes={"confidence": policy_result.confidence},
    )
    return {"confidence": policy_result.confidence, "verification_issues": []}
