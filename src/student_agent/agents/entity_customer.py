"""Entity & Customer Agent --- Le Viet Hoang phu trach (ho tro chay end-to-end de dong goi submission.zip)."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from ..trace import TraceWriter

ACTOR_NAME = "entity-agent"


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
class EntityResult:
    status: str = "not_found"  # "resolved" | "ambiguous" | "not_found"
    resolved_order_ids: list[str] = field(default_factory=list)
    rejected_candidates: list[str] = field(default_factory=list)
    confidence: float = 0.0
    ambiguous: bool = False
    customer_unique_id: str | None = None
    related_order_ids: list[str] = field(default_factory=list)
    order_ids: list[str] = field(default_factory=list)
    item_ids: list[str] = field(default_factory=list)
    seller_ids: list[str] = field(default_factory=list)
    payment_references: list[str] = field(default_factory=list)
    shipment_ids: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    orders_data: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def entity_id(self) -> str | None:
        return self.resolved_order_ids[0] if self.resolved_order_ids else None


async def run(case: dict[str, Any], gateway: Any, trace: TraceWriter) -> EntityResult:
    case_id = str(case["case_id"])
    trace.emit(
        case_id=case_id,
        event_type="task_assigned",
        actor="coordinator",
        target=ACTOR_NAME,
    )

    claimed_order_id = (
        case.get("customer_request", {}).get("claimed_order_id")
        if isinstance(case.get("customer_request"), dict)
        else None
    )
    candidates: list[str] = []
    if isinstance(claimed_order_id, str) and claimed_order_id:
        candidates.append(claimed_order_id)
    for cand in case.get("candidate_order_ids", []) or []:
        if isinstance(cand, str) and cand and cand not in candidates:
            candidates.append(cand)

    customer_hint = case.get("customer_unique_id_hint")
    include_cust = bool(
        case.get("investigation_scope", {}).get("include_customer_history", True)
    )

    evidence_refs: list[str] = []
    resolved: list[str] = []
    rejected: list[str] = []
    orders_data: dict[str, dict[str, Any]] = {}
    related_orders: list[str] = []
    customer_unique_id: str | None = (
        str(customer_hint) if isinstance(customer_hint, str) and customer_hint else None
    )

    # Run get_customer_history and get_order(claimed_order_id) concurrently
    async def _fetch_cust():
        if not (include_cust and customer_unique_id):
            return None
        try:
            return await gateway.call(
                "get_customer_history",
                case_id=case_id,
                customer_unique_id=customer_unique_id,
            )
        except Exception:
            return None

    async def _fetch_ord(oid: str):
        try:
            return oid, await gateway.call("get_order", case_id=case_id, order_id=oid)
        except Exception:
            return oid, None

    real_candidates = [c for c in candidates if not c.startswith("candidate-")]
    synthetic_candidates = [c for c in candidates if c.startswith("candidate-")]
    rejected.extend(synthetic_candidates)

    cust_task = _fetch_cust()
    ord_tasks = [_fetch_ord(c) for c in real_candidates]
    gathered = await asyncio.gather(cust_task, *ord_tasks)

    cust_ev = gathered[0]
    ord_results = gathered[1:]

    if isinstance(cust_ev, dict) and cust_ev.get("evidence_ref"):
        ev_ref = str(cust_ev["evidence_ref"])
        evidence_refs.append(ev_ref)
        trace.emit(
            case_id=case_id,
            event_type="tool_result_consumed",
            actor=ACTOR_NAME,
            tool_name="get_customer_history",
            evidence_refs=[ev_ref],
        )
        cdata = cust_ev.get("data")
        if isinstance(cdata, dict):
            if cdata.get("customer_unique_id"):
                customer_unique_id = str(cdata["customer_unique_id"])
            for row in cdata.get("orders", []) or []:
                if isinstance(row, dict) and row.get("order_id"):
                    related_orders.append(str(row["order_id"]))

    for cand, ord_ev in ord_results:
        if isinstance(ord_ev, dict) and ord_ev.get("evidence_ref"):
            ev_ref = str(ord_ev["evidence_ref"])
            evidence_refs.append(ev_ref)
            trace.emit(
                case_id=case_id,
                event_type="tool_result_consumed",
                actor=ACTOR_NAME,
                tool_name="get_order",
                evidence_refs=[ev_ref],
            )
            odata = ord_ev.get("data")
            if isinstance(odata, dict) and odata.get("order_id"):
                resolved.append(str(odata["order_id"]))
                orders_data[str(odata["order_id"])] = odata
            else:
                rejected.append(cand)
        else:
            rejected.append(cand)

    resolved = _unique_preserve_order(resolved)
    rejected = _unique_preserve_order([r for r in candidates if r not in resolved])
    related_orders = _unique_preserve_order(related_orders or resolved)

    if len(resolved) == 1:
        status = "resolved"
        ambiguous = False
        conf = 0.92 if resolved[0] == claimed_order_id else 0.82
    elif len(resolved) > 1:
        if claimed_order_id and claimed_order_id in resolved:
            status = "resolved"
            ambiguous = False
            conf = 0.88
            for extra in resolved:
                if extra != claimed_order_id and extra not in rejected:
                    rejected.append(extra)
            resolved = [claimed_order_id]
        else:
            status = "ambiguous"
            ambiguous = True
            conf = 0.55
    else:
        status = "not_found"
        ambiguous = True
        conf = 0.25

    res = EntityResult(
        status=status,
        resolved_order_ids=resolved,
        rejected_candidates=rejected,
        confidence=round(conf, 2),
        ambiguous=ambiguous,
        customer_unique_id=customer_unique_id,
        related_order_ids=related_orders,
        order_ids=list(resolved),
        evidence_refs=_unique_preserve_order(evidence_refs, max_items=30),
        orders_data=orders_data,
    )

    trace.emit(
        case_id=case_id,
        event_type="handoff",
        actor=ACTOR_NAME,
        target="coordinator",
        decision_code=status,
        evidence_refs=res.evidence_refs[:20] or None,
    )
    return res
