"""Kiem thu Entity & Customer Agent (Le Viet Hoang).

Khong goi MCP that: gateway duoc gia lap nhung van validate evidence bang
`Contracts` that, va trace ghi bang `TraceWriter` that (schema trace-event-v1).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from student_agent.agents import entity_customer
from student_agent.contracts import Contracts
from student_agent.trace import TraceWriter

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = Contracts(ROOT / "contracts" / "schemas")

HEX_A = "a" * 32
HEX_B = "b" * 32
SYNTHETIC = "candidate-001"


def _order_data(
    order_id: str,
    *,
    customer_id: str = "customer-row-a",
    purchase: str = "2018-05-11T09:00:00-03:00",
    estimated: str = "2018-05-21T09:00:00-03:00",
) -> dict[str, Any]:
    return {
        "order_id": order_id,
        "customer_id": customer_id,
        "order_status": "delivered",
        "order_purchase_timestamp": purchase,
        "order_approved_at": purchase,
        "order_delivered_carrier_date": "2018-05-13T09:00:00-03:00",
        "order_delivered_customer_date": "2018-05-20T09:00:00-03:00",
        "order_estimated_delivery_date": estimated,
    }


class FakeGateway:
    """Gateway gia lap: tra evidence dung schema, ghi lai moi call."""

    def __init__(
        self,
        *,
        orders: dict[str, dict[str, Any]] | None = None,
        histories: dict[str, dict[str, Any]] | None = None,
        fail_orders: set[str] | None = None,
        fail_history: set[str] | None = None,
    ) -> None:
        self.orders = orders or {}
        self.histories = histories or {}
        self.fail_orders = fail_orders or set()
        self.fail_history = fail_history or set()
        self.calls: list[tuple[str, str, dict[str, str]]] = []
        self.returned_refs: list[str] = []
        self._counter = 0

    def _evidence(self, domain: str, data: dict[str, Any]) -> dict[str, Any]:
        self._counter += 1
        evidence = {
            "schema_version": "day09-mcp-evidence-v1",
            "evidence_ref": f"ev_{self._counter:04d}FakeEvidenceRef00",
            "result_hash": "sha256:" + "0" * 64,
            "domain": domain,
            "data": data,
            "warnings": [],
        }
        SCHEMAS.validate_evidence(evidence, "fake gateway")
        self.returned_refs.append(evidence["evidence_ref"])
        return evidence

    async def call(self, tool_name: str, *, case_id: str, **arguments: str) -> dict[str, Any]:
        self.calls.append((tool_name, case_id, dict(arguments)))
        if tool_name == "get_order":
            order_id = arguments["order_id"]
            if order_id in self.fail_orders or order_id not in self.orders:
                raise RuntimeError(f"MCP tool get_order failed: Error executing tool get_order")
            return self._evidence("order", self.orders[order_id])
        if tool_name == "get_customer_history":
            unique_id = arguments["customer_unique_id"]
            if unique_id in self.fail_history or unique_id not in self.histories:
                raise RuntimeError("MCP tool get_customer_history failed: Error executing tool")
            return self._evidence("customer", self.histories[unique_id])
        raise AssertionError(f"unexpected tool: {tool_name}")


def _case(
    *,
    case_id: str = "L3B_CASE_001",
    claimed: str | None = HEX_A,
    candidates: list[str] | None = None,
    hint: str | None = "customer-0000000000a",
    include_history: bool = True,
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "opened_at": "2018-01-01T09:00:00-03:00",
        "customer_request": {
            "language": "vi",
            "message": "dieu tra da nguon",
            "claimed_order_id": claimed,
            "claims": [{"claim_id": "claim-a", "topic": "late_delivery_logistics"}],
        },
        "policy_version": "EC_POLICY_V2",
        "candidate_order_ids": [item for item in [claimed, SYNTHETIC] if item]
        if candidates is None
        else candidates,
        "investigation_scope": {
            "include_customer_history": include_history,
            "include_product_context": True,
            "require_independent_verification": True,
        },
        "customer_unique_id_hint": hint,
    }


def _trace(tmp_path: Path) -> tuple[TraceWriter, Path]:
    path = tmp_path / "trace.jsonl"
    return TraceWriter(path, SCHEMAS), path


def _events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _history(unique_id: str, orders: list[dict[str, Any]]) -> dict[str, Any]:
    return {"customer_unique_id": unique_id, "orders": orders}


# --------------------------------------------------------------------------- tests


def test_exact_claimed_order_resolves_with_customer_context(tmp_path: Path) -> None:
    hint = "customer-0000000000a"
    gateway = FakeGateway(
        orders={HEX_A: _order_data(HEX_A)},
        histories={
            hint: _history(
                hint,
                [
                    _order_data(HEX_A),
                    # cung order_id nhung moc thoi gian khac -> conflict nguon
                    _order_data(HEX_A, purchase="2017-12-20T09:00:00-03:00"),
                ],
            )
        },
    )
    trace, trace_path = _trace(tmp_path)

    result = asyncio.run(entity_customer.run(_case(), gateway, trace))

    assert result.status == "resolved"
    assert result.resolved_order_ids == [HEX_A]
    assert result.order_ids == [HEX_A]
    assert result.rejected_candidates == [SYNTHETIC]
    assert result.customer_unique_id == hint
    assert result.related_order_ids == [HEX_A]
    assert result.confidence == 0.85
    assert result.ambiguous is False
    assert any(note.startswith("order_history_conflict:") for note in result.notes)
    # chi 2 MCP call: exact order + customer history
    assert [call[0] for call in gateway.calls] == ["get_order", "get_customer_history"]
    assert len(result.evidence_refs) == 2
    assert all(call[1] == "L3B_CASE_001" for call in gateway.calls)


def test_synthetic_candidate_is_rejected_without_mcp_call(tmp_path: Path) -> None:
    gateway = FakeGateway(orders={HEX_A: _order_data(HEX_A)})
    trace, _ = _trace(tmp_path)

    result = asyncio.run(entity_customer.run(_case(), gateway, trace))

    probed_ids = [call[2].get("order_id") for call in gateway.calls if call[0] == "get_order"]
    assert SYNTHETIC not in probed_ids
    assert SYNTHETIC in result.rejected_candidates
    assert any(f"invalid_shape:{SYNTHETIC}" in note for note in result.notes)


def test_unknown_claimed_order_falls_back_to_valid_candidate(tmp_path: Path) -> None:
    hint = "customer-0000000000b"
    gateway = FakeGateway(
        orders={HEX_B: _order_data(HEX_B)},
        histories={hint: _history(hint, [_order_data(HEX_B)])},
    )
    trace, _ = _trace(tmp_path)
    case = _case(claimed=HEX_A, candidates=[HEX_A, HEX_B, SYNTHETIC], hint=hint)

    result = asyncio.run(entity_customer.run(case, gateway, trace))

    assert result.status == "resolved"
    assert result.resolved_order_ids == [HEX_B]
    assert HEX_A in result.rejected_candidates
    assert result.confidence == 0.65
    assert any("resolved_without_claimed_exact_match" in note for note in result.notes)


def test_two_resolved_candidates_mark_ambiguous(tmp_path: Path) -> None:
    gateway = FakeGateway(orders={HEX_A: _order_data(HEX_A), HEX_B: _order_data(HEX_B)})
    trace, _ = _trace(tmp_path)
    case = _case(claimed=None, candidates=[HEX_A, HEX_B], hint=None)

    result = asyncio.run(entity_customer.run(case, gateway, trace))

    assert result.status == "ambiguous"
    assert result.ambiguous is True
    assert result.confidence == 0.5
    assert sorted(result.resolved_order_ids) == sorted([HEX_A, HEX_B])


def test_no_candidate_found_returns_not_found(tmp_path: Path) -> None:
    gateway = FakeGateway(orders={})
    trace, _ = _trace(tmp_path)

    result = asyncio.run(entity_customer.run(_case(hint=None), gateway, trace))

    assert result.status == "not_found"
    assert result.resolved_order_ids == []
    assert result.confidence == 0.0
    assert set(result.rejected_candidates) == {HEX_A, SYNTHETIC}
    assert result.customer_unique_id is None


def test_customer_history_mismatch_keeps_unique_id_null(tmp_path: Path) -> None:
    hint = "customer-0000000000c"
    gateway = FakeGateway(
        orders={HEX_A: _order_data(HEX_A)},
        histories={hint: _history(hint, [_order_data(HEX_B)])},
    )
    trace, _ = _trace(tmp_path)

    result = asyncio.run(entity_customer.run(_case(hint=hint), gateway, trace))

    assert result.customer_unique_id is None
    assert result.related_order_ids == [HEX_B]
    assert result.confidence == 0.65
    assert "customer_history_mismatch" in result.notes


def test_history_skipped_by_scope_avoids_extra_mcp_call(tmp_path: Path) -> None:
    gateway = FakeGateway(orders={HEX_A: _order_data(HEX_A)})
    trace, _ = _trace(tmp_path)

    result = asyncio.run(entity_customer.run(_case(include_history=False), gateway, trace))

    assert [call[0] for call in gateway.calls] == ["get_order"]
    assert result.confidence == 0.85
    assert "customer_history_skipped_by_scope" in result.notes


def test_trace_records_lifecycle_events_and_evidence_linkage(tmp_path: Path) -> None:
    hint = "customer-0000000000a"
    gateway = FakeGateway(
        orders={HEX_A: _order_data(HEX_A)},
        histories={hint: _history(hint, [_order_data(HEX_A)])},
    )
    trace, trace_path = _trace(tmp_path)

    result = asyncio.run(entity_customer.run(_case(hint=hint), gateway, trace))
    events = _events(trace_path)

    assert [event["event_type"] for event in events] == [
        "task_assigned",
        "tool_result_consumed",
        "tool_result_consumed",
        "handoff",
    ]
    assert all(event["actor"] == "entity-agent" for event in events)
    assert all(event["case_id"] == "L3B_CASE_001" for event in events)
    consumed = [
        ref
        for event in events
        if event["event_type"] == "tool_result_consumed"
        for ref in event.get("evidence_refs", [])
    ]
    assert consumed == result.evidence_refs
    handoff = events[-1]
    assert handoff["target"] == "coordinator"
    assert handoff["decision_code"] == "entity_resolved"
    assert set(handoff["evidence_refs"]) <= set(result.evidence_refs)


def test_evidence_refs_are_only_the_ones_returned_by_gateway(tmp_path: Path) -> None:
    hint = "customer-0000000000a"
    gateway = FakeGateway(
        orders={HEX_A: _order_data(HEX_A)},
        histories={hint: _history(hint, [_order_data(HEX_A)])},
    )
    trace, _ = _trace(tmp_path)

    result = asyncio.run(entity_customer.run(_case(hint=hint), gateway, trace))

    assert result.evidence_refs == list(dict.fromkeys(result.evidence_refs))
    assert set(result.evidence_refs) <= set(gateway.returned_refs)
    assert all(ref.startswith("ev_") and len(ref) >= 23 for ref in result.evidence_refs)


def test_unexpected_gateway_error_is_not_swallowed(tmp_path: Path) -> None:
    class BrokenGateway(FakeGateway):
        async def call(self, tool_name: str, *, case_id: str, **arguments: str) -> dict[str, Any]:
            raise ValueError(f"contract violated for {tool_name}")

    trace, _ = _trace(tmp_path)
    with pytest.raises(ValueError):
        asyncio.run(entity_customer.run(_case(), BrokenGateway(), trace))


def test_missing_case_id_is_rejected(tmp_path: Path) -> None:
    trace, _ = _trace(tmp_path)
    with pytest.raises(ValueError):
        asyncio.run(entity_customer.run({"customer_request": {}}, FakeGateway(), trace))


def test_entity_result_feeds_coordinator_output_builder(tmp_path: Path) -> None:
    """Tich hop voi workflow.py: EntityResult phai map duoc sang output L3B."""
    from student_agent.workflow import _build_output

    hint = "customer-0000000000a"
    gateway = FakeGateway(
        orders={HEX_A: _order_data(HEX_A)},
        histories={hint: _history(hint, [_order_data(HEX_A)])},
    )
    trace, _ = _trace(tmp_path)
    case = _case(hint=hint)
    result = asyncio.run(entity_customer.run(case, gateway, trace))

    shipment = SimpleNamespace(
        verdict="on_time",
        late_seller_ids=[],
        timeline_complete=True,
        item_ids=["item-a"],
        seller_ids=["seller-a"],
        shipment_ids=[],
        evidence_refs=[],
    )
    payment = SimpleNamespace(
        verdict="reconciled",
        captured_total_brl=100.0,
        refunded_total_brl=0.0,
        refundable_total_brl=0.0,
        payment_references=["credit_card:1:100.00"],
        evidence_refs=[],
    )
    policy = SimpleNamespace(
        primary_issue="unsupported_claim",
        secondary_issues=[],
        case_status="no_action",
        ranked_causes=[{"cause_code": "NO_DEFECT_FOUND", "rank": 1}],
        responsible_parties=[{"party_type": "platform", "party_id": None}],
        data_conflicts=[],
        recommended_refund_brl=0.0,
        refund_lines=[],
        resolution_actions=["close_case_no_action"],
        confidence=result.confidence,
        evidence_refs=[],
    )

    output = _build_output(
        case_id=case["case_id"],
        case=case,
        entity_result=result,
        shipment_result=shipment,
        payment_result=payment,
        policy_result=policy,
        confidence=result.confidence,
        all_evidence_refs=result.evidence_refs,
    )

    assert output["affected_entities"]["order_ids"] == [HEX_A]
    assert output["entity_resolution"] == {
        "status": "resolved",
        "resolved_order_ids": [HEX_A],
        "rejected_candidates": [SYNTHETIC],
        "confidence": 0.85,
    }
    assert output["customer_context"]["customer_unique_id"] == hint
    assert output["customer_context"]["related_order_ids"] == [HEX_A]
    SCHEMAS.validate_output(output, "integration output")
