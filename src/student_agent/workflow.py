"""L3B Coordinator Workflow --- Mai Tien Huy phu trach.

Orchestrates all specialist agents:
  1. entity resolution
  2. parallel: order_agent + payment_agent
  3. policy_agent
  4. verifier_agent
  5. build output -> validate schema
"""
from __future__ import annotations

import asyncio
import functools
import hashlib
import json
import logging
from typing import Any

from .agents import entity_customer, order_shipment, payment_policy
from .mcp_gateway import EvidenceGateway
from .trace import TraceWriter

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# MCP Cache: tool_name + params + case_id -> result
# ---------------------------------------------------------------------------

class _GatewayWithCache:
    """Wraps EvidenceGateway with per-case caching to avoid duplicate MCP calls."""

    def __init__(self, gateway: EvidenceGateway) -> None:
        self._gw = gateway
        self._cache: dict[str, dict[str, Any]] = {}  # keyed by cache_key

    @staticmethod
    def _make_key(tool_name: str, case_id: str, kwargs: dict[str, str]) -> str:
        payload = {"tool": tool_name, "case_id": case_id, **kwargs}
        raw = json.dumps(payload, sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    async def call(self, tool_name: str, *, case_id: str, **kwargs: str) -> dict[str, Any]:
        key = self._make_key(tool_name, case_id, kwargs)
        if key in self._cache:
            logger.debug("[%s] cache hit: %s %s", case_id, tool_name, kwargs)
            return self._cache[key]
        # Retry logic: up to 2 retries for transient errors, not 403
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                result = await self._gw.call(tool_name, case_id=case_id, **kwargs)
                self._cache[key] = result
                return result
            except RuntimeError as exc:
                msg = str(exc)
                if "403" in msg or "401" in msg or "forbidden" in msg.lower():
                    raise  # do not retry auth errors
                last_exc = exc
                if attempt < 2:
                    await asyncio.sleep(0.3 * (attempt + 1))
        raise last_exc  # type: ignore[misc]

    async def list_tools(self) -> list[str]:
        return await self._gw.list_tools()

    def clear_case_cache(self, case_id: str) -> None:
        """Remove entries for a specific case to avoid cross-case leak."""
        to_remove = [k for k, v in self._cache.items()
                     if isinstance(v, dict) and v.get("case_id") == case_id]
        for k in to_remove:
            del self._cache[k]


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def solve_case(
    case: dict[str, Any], gateway: EvidenceGateway, trace: TraceWriter
) -> dict[str, Any]:
    """L3B coordinator + specialist agents workflow."""
    case_id = case["case_id"]

    # Isolate per-case gateway cache
    cached_gw = _GatewayWithCache(gateway)

    trace.emit(
        case_id=case_id,
        event_type="case_received",
        actor="coordinator",
        attributes={"policy_version": case.get("policy_version", "")},
    )

    # -----------------------------------------------------------------------
    # Pha 1: Entity Resolution
    # -----------------------------------------------------------------------
    entity_result = await entity_customer.run(case, cached_gw, trace)

    # -----------------------------------------------------------------------
    # Pha 2: Parallel specialist agents
    # -----------------------------------------------------------------------
    shipment_task = asyncio.create_task(
        order_shipment.run(case, entity_result, cached_gw, trace)
    )
    payment_task = asyncio.create_task(
        payment_policy.run_payment(case, entity_result, cached_gw, trace)
    )

    shipment_result, payment_result = await asyncio.gather(shipment_task, payment_task)

    # -----------------------------------------------------------------------
    # Pha 3: Policy Engine
    # -----------------------------------------------------------------------
    policy_result = payment_policy.decide_policy(
        case, entity_result, shipment_result, payment_result, trace
    )

    # -----------------------------------------------------------------------
    # Pha 4: Verifier
    # -----------------------------------------------------------------------
    verification = payment_policy.verify_and_calibrate(
        case, entity_result, shipment_result, payment_result, policy_result, trace
    )
    confidence = verification["confidence"]

    # -----------------------------------------------------------------------
    # Pha 5: Build output
    # -----------------------------------------------------------------------
    all_evidence_refs: list[str] = _deduplicate(
        entity_result.evidence_refs
        + shipment_result.evidence_refs
        + payment_result.evidence_refs
        + policy_result.evidence_refs
    )[:30]

    output = _build_output(
        case_id=case_id,
        case=case,
        entity_result=entity_result,
        shipment_result=shipment_result,
        payment_result=payment_result,
        policy_result=policy_result,
        confidence=confidence,
        all_evidence_refs=all_evidence_refs,
    )

    trace.emit(
        case_id=case_id,
        event_type="case_finalized",
        actor="coordinator",
        decision_code=output["assessment"]["primary_issue"],
        evidence_refs=all_evidence_refs or None,
        attributes={
            "confidence": confidence,
            "case_status": output["assessment"]["case_status"],
        },
    )

    # Clear cache entries for this case to avoid cross-case leak
    cached_gw.clear_case_cache(case_id)

    return output


# ---------------------------------------------------------------------------
# Output builder
# ---------------------------------------------------------------------------

def _build_output(
    *,
    case_id: str,
    case: dict[str, Any],
    entity_result,
    shipment_result,
    payment_result,
    policy_result,
    confidence: float,
    all_evidence_refs: list[str],
) -> dict[str, Any]:
    claims = case.get("customer_request", {}).get("claims", [])
    claim_assessments = _build_claim_assessments(claims, policy_result, all_evidence_refs)

    output: dict[str, Any] = {
        "schema_version": "day09-l3b-output-v2",
        "case_id": case_id,
        "assessment": {
            "primary_issue": policy_result.primary_issue,
            "secondary_issues": policy_result.secondary_issues,
            "case_status": policy_result.case_status,
            "confidence": confidence,
        },
        "affected_entities": {
            "order_ids": entity_result.order_ids[:20],
            "item_ids": entity_result.item_ids[:20],
            "seller_ids": entity_result.seller_ids[:20],
            "payment_references": entity_result.payment_references[:20],
            "shipment_ids": entity_result.shipment_ids[:20],
        },
        "entity_resolution": {
            "status": entity_result.status,
            "resolved_order_ids": entity_result.resolved_order_ids[:20],
            "rejected_candidates": entity_result.rejected_candidates[:20],
            "confidence": entity_result.confidence,
        },
        "customer_context": {
            "customer_unique_id": entity_result.customer_unique_id,
            "related_order_ids": entity_result.related_order_ids[:20],
        },
        "shipment_analysis": {
            "verdict": shipment_result.verdict,
            "late_seller_ids": shipment_result.late_seller_ids[:20],
            "timeline_complete": shipment_result.timeline_complete,
        },
        "payment_analysis": {
            "verdict": payment_result.verdict,
            "captured_total_brl": payment_result.captured_total_brl,
            "refunded_total_brl": payment_result.refunded_total_brl,
            "refundable_total_brl": payment_result.refundable_total_brl,
        },
        "root_cause_analysis": {
            "ranked_causes": policy_result.ranked_causes[:5],
            "responsible_parties": policy_result.responsible_parties[:5],
        },
        "evidence_refs": all_evidence_refs,
        "data_conflicts": policy_result.data_conflicts[:5],
        "financial_resolution": {
            "currency": "BRL",
            "recommended_refund_brl": policy_result.recommended_refund_brl,
            "refund_lines": policy_result.refund_lines[:10],
        },
        "resolution_actions": policy_result.resolution_actions[:8],
    }

    if claim_assessments:
        output["claim_assessments"] = claim_assessments[:5]

    return output


def _build_claim_assessments(
    claims: list[dict[str, Any]],
    policy_result,
    evidence_refs: list[str],
) -> list[dict[str, Any]]:
    assessments: list[dict[str, Any]] = []
    primary = policy_result.primary_issue
    for claim in claims:
        cid = claim.get("claim_id", "")
        topic = claim.get("topic", "")
        # Determine verdict based on alignment with primary issue
        if primary == "insufficient_evidence":
            verdict = "insufficient_evidence"
            conf = 0.3
        elif topic in (primary, *policy_result.secondary_issues):
            verdict = "supported"
            conf = policy_result.confidence if hasattr(policy_result, "confidence") else 0.7
        elif topic in ("requested_full_refund",):
            if policy_result.recommended_refund_brl > 0:
                verdict = "partially_supported"
                conf = 0.6
            else:
                verdict = "unsupported"
                conf = 0.4
        else:
            verdict = "insufficient_evidence"
            conf = 0.3
        assessments.append({
            "claim_id": cid,
            "verdict": verdict,
            "confidence": round(conf, 2),
            "evidence_refs": evidence_refs[:10],
        })
    return assessments


def _deduplicate(lst: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for v in lst:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out
