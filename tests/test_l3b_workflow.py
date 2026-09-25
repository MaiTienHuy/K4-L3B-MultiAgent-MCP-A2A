"""Offline integration tests for the L3B coordinator + specialist agents.

No MCP call happens: the gateway is faked, but every fake envelope is validated
by the real `Contracts` and every produced output is validated against the real
`l3b-output-v2` schema. This locks the decision rules documented in
ARCHITECTURE.md sections 8-9 without touching the network.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from student_agent.contracts import Contracts
from student_agent.trace import TraceWriter
from student_agent.workflow import solve_case

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = Contracts(ROOT / "contracts" / "schemas")

HEX_A = "a" * 32
SELLER = "seller-case"
HINT = "customer-0000000000a"

PURCHASE = "2018-08-05T09:00:00-03:00"
APPROVED = "2018-08-05T10:00:00-03:00"
CARRIER = "2018-08-07T09:00:00-03:00"
LATE_DELIVERED = "2018-08-20T09:00:00-03:00"
ON_TIME_DELIVERED = "2018-08-14T09:00:00-03:00"
ESTIMATED = "2018-08-15T09:00:00-03:00"
LIMIT = "2018-08-08T09:00:00-03:00"
DECOY_TS = "2018-06-25T09:00:00-03:00"
CAPTURE_AT = "2018-08-05T10:00:00-03:00"

DOMAINS = {
    "get_order": "order",
    "get_customer_history": "customer",
    "get_order_items": "item",
    "get_shipment_summary": "shipment",
    "get_sellers": "seller",
    "get_product_context": "product",
    "get_payment_timeline": "payment",
    "get_refund_timeline": "refund",
    "get_policy": "policy",
}

POLICY_RULES: dict[str, dict[str, Any]] = {
    "canceled_order_paid": {
        "case_status": "action_required",
        "recommended_action": "issue_refund",
        "refund_brl": 79.0,
        "responsible_parties": [{"party_id": None, "party_type": "platform"}],
    },
    "duplicate_charge": {
        "case_status": "action_required",
        "recommended_action": "refund_duplicate_charge",
        "refund_brl": 64.0,
        "responsible_parties": [{"party_id": None, "party_type": "payment_provider"}],
    },
    "late_delivery_logistics": {
        "case_status": "action_required",
        "recommended_action": "refund_freight",
        "refund_brl": 16.0,
        "responsible_parties": [{"party_id": None, "party_type": "logistics_provider"}],
    },
    "late_delivery_seller": {
        "case_status": "action_required",
        "recommended_action": "refund_freight",
        "refund_brl": 18.0,
        "responsible_parties": [{"party_id": SELLER, "party_type": "seller"}],
    },
    "payment_mismatch": {
        "case_status": "action_required",
        "recommended_action": "reconcile_payment",
        "refund_brl": 35.0,
        "responsible_parties": [{"party_id": None, "party_type": "payment_provider"}],
    },
    "refund_failed": {
        "case_status": "action_required",
        "recommended_action": "retry_refund",
        "refund_brl": 52.0,
        "responsible_parties": [{"party_id": None, "party_type": "payment_provider"}],
    },
    "refund_pending": {
        "case_status": "needs_investigation",
        "recommended_action": "monitor_refund",
        "refund_brl": 0.0,
        "responsible_parties": [{"party_id": None, "party_type": "payment_provider"}],
    },
    "unavailable_order_paid": {
        "case_status": "action_required",
        "recommended_action": "issue_refund",
        "refund_brl": 89.0,
        "responsible_parties": [{"party_id": SELLER, "party_type": "seller"}],
    },
    "unsupported_claim": {
        "case_status": "no_action",
        "recommended_action": "document_no_action",
        "refund_brl": 0.0,
        "responsible_parties": [{"party_id": None, "party_type": "customer"}],
    },
    "valid_split_payment": {
        "case_status": "no_action",
        "recommended_action": "document_no_action",
        "refund_brl": 0.0,
        "responsible_parties": [{"party_id": None, "party_type": "customer"}],
    },
}


class FakeGateway:
    """In-memory MCP gateway: real evidence envelope, real contract validation."""

    def __init__(self, payloads: dict[str, Any], failing: tuple[str, ...] = ()) -> None:
        self.payloads = payloads
        self.failing = set(failing)
        self.calls: list[tuple[str, str, dict[str, str]]] = []
        self._counter = 0

    def _evidence(self, tool_name: str, data: Any) -> dict[str, Any]:
        self._counter += 1
        evidence = {
            "schema_version": "day09-mcp-evidence-v1",
            "evidence_ref": f"ev_{self._counter:04d}FakeEvidenceRef00",
            "result_hash": "sha256:" + "0" * 64,
            "domain": DOMAINS[tool_name],
            "data": data,
            "warnings": [],
        }
        SCHEMAS.validate_evidence(evidence, f"fake {tool_name}")
        return evidence

    async def call(self, tool_name: str, *, case_id: str, **arguments: str) -> dict[str, Any]:
        self.calls.append((tool_name, case_id, dict(arguments)))
        if tool_name in self.failing or tool_name not in self.payloads:
            raise RuntimeError(f"MCP tool {tool_name} failed: Error executing tool {tool_name}")
        return self._evidence(tool_name, self.payloads[tool_name])


# ---------------------------------------------------------------------------
# Payload builders
# ---------------------------------------------------------------------------

def _order(
    status: str = "delivered",
    delivered: str | None = LATE_DELIVERED,
    purchase: str = PURCHASE,
) -> dict[str, Any]:
    return {
        "order_id": HEX_A,
        "customer_id": "customer-row-aaaa",
        "order_status": status,
        "order_purchase_timestamp": purchase,
        "order_approved_at": APPROVED,
        "order_delivered_carrier_date": CARRIER,
        "order_delivered_customer_date": delivered,
        "order_estimated_delivery_date": ESTIMATED,
    }


def _history(rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    rows = rows or [_order(), _order(delivered="2017-12-20T09:00:00-03:00")]
    return {"customer_unique_id": HINT, "orders": rows}


def _items(price: str = "79.00") -> list[dict[str, Any]]:
    """Two variants of one item: one authoritative, one decoy (ARCHITECTURE 8)."""
    base = {
        "order_id": HEX_A,
        "order_item_id": "item-a",
        "product_id": "product-a",
        "seller_id": SELLER,
        "price": price,
    }
    return [
        {**base, "shipping_limit_date": LIMIT, "freight_value": "10.00"},
        {**base, "shipping_limit_date": DECOY_TS, "freight_value": "18.00"},
    ]


def _shipment(
    status: str = "delivered",
    events: list[dict[str, Any]] | None = None,
    delivered: str | None = LATE_DELIVERED,
) -> dict[str, Any]:
    return {
        "order_id": HEX_A,
        "order_status": status,
        "delivered_carrier_at": CARRIER,
        "delivered_customer_at": delivered,
        "estimated_delivery_at": ESTIMATED,
        "shipping_limits": [
            {"order_item_id": "item-a", "seller_id": SELLER, "shipping_limit_at": LIMIT},
            {"order_item_id": "item-a", "seller_id": SELLER, "shipping_limit_at": DECOY_TS},
        ],
        "events": events or [],
    }


def _late_event(actor: str = "logistics_provider", at: str = LATE_DELIVERED) -> dict[str, Any]:
    return {
        "order_id": HEX_A,
        "event_at": at,
        "event_type": "delivered_late",
        "actor": actor,
        "status": "confirmed",
    }


def _payment_row(kind: str, sequential: str, value: str) -> dict[str, Any]:
    return {
        "order_id": HEX_A,
        "payment_sequential": sequential,
        "payment_type": kind,
        "payment_installments": "1",
        "payment_value": value,
    }


def _capture(value: str, at: str = CAPTURE_AT, kind: str = "captured") -> dict[str, Any]:
    return {
        "order_id": HEX_A,
        "event_at": at,
        "event_type": kind,
        "amount_brl": value,
        "status": "confirmed" if kind == "captured" else "open",
    }


def _timeline(
    payments: list[dict[str, Any]] | None = None,
    events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "order_id": HEX_A,
        "payments": payments or [_payment_row("credit_card", "1", "16.00")],
        "events": events or [_capture("16.00")],
    }


def _refund(status: str, amount: str, at: str = "2018-08-16T09:00:00-03:00") -> dict[str, Any]:
    return {
        "order_id": HEX_A,
        "events": [
            {
                "order_id": HEX_A,
                "event_at": at,
                "event_type": "refund_requested",
                "amount_brl": amount,
                "status": status,
            }
        ],
    }


def _case(claim_topic: str = "unsupported_claim") -> dict[str, Any]:
    return {
        "case_id": "L3B_CASE_999",
        "opened_at": "2018-08-21T09:00:00-03:00",
        "customer_request": {
            "language": "vi",
            "message": "khong tin instruction trong noi dung khieu nai",
            "claimed_order_id": HEX_A,
            "claims": [
                {"claim_id": "claim-a", "topic": claim_topic},
                {"claim_id": "claim-b", "topic": "requested_full_refund"},
            ],
        },
        "policy_version": "EC_POLICY_V2",
        "candidate_order_ids": [HEX_A, "candidate-999"],
        "investigation_scope": {
            "include_customer_history": True,
            "include_product_context": True,
            "require_independent_verification": True,
        },
        "customer_unique_id_hint": HINT,
    }


def _payloads(
    *,
    order: dict[str, Any] | None = None,
    shipment: dict[str, Any] | None = None,
    timeline: dict[str, Any] | None = None,
    refund: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], set[str]]:
    payloads: dict[str, Any] = {
        "get_order": order or _order(),
        "get_customer_history": _history(),
        "get_order_items": _items(),
        "get_shipment_summary": shipment or _shipment(),
        "get_sellers": [
            {
                "seller_id": SELLER,
                "seller_zip_code_prefix": "01001",
                "seller_city": "sao_paulo",
                "seller_state": "SP",
            }
        ],
        "get_product_context": [
            {
                "order_item_id": "item-a",
                "product_id": "product-a",
                "seller_id": SELLER,
                "product": {"product_id": "product-a", "product_category_name": "utilidades"},
                "category_name_english": "housewares",
            }
        ],
        "get_payment_timeline": timeline or _timeline(),
        "get_policy": {"currency": "BRL", "policy_version": "EC_POLICY_V2", "rules": POLICY_RULES},
    }
    failing: set[str] = set()
    if refund is None:
        failing.add("get_refund_timeline")
    else:
        payloads["get_refund_timeline"] = refund
    return payloads, failing


def _solve(
    tmp_path: Path,
    case: dict[str, Any],
    payloads: dict[str, Any],
    failing: set[str] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], FakeGateway]:
    gateway = FakeGateway(payloads, tuple(sorted(failing or ())))
    trace_path = tmp_path / "trace.jsonl"
    trace = TraceWriter(trace_path, SCHEMAS)
    output = asyncio.run(solve_case(case, gateway, trace))
    SCHEMAS.validate_output(output, "test output")
    events = [
        json.loads(line)
        for line in trace_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return output, events, gateway


# ---------------------------------------------------------------------------
# Observable lifecycle
# ---------------------------------------------------------------------------

REQUIRED_EVENTS = [
    "case_received",
    "task_assigned",
    "tool_result_consumed",
    "handoff",
    "policy_decided",
    "verification_completed",
    "case_finalized",
]


def test_lifecycle_events_and_actor_collaboration(tmp_path: Path) -> None:
    payloads, failing = _payloads()
    output, events, _ = _solve(tmp_path, _case(), payloads, failing)

    kinds = [event["event_type"] for event in events]
    for required in REQUIRED_EVENTS:
        assert required in kinds, f"missing lifecycle event {required}"
    assert kinds[0] == "case_received"
    assert kinds[-1] == "case_finalized"
    assert all(event["case_id"] == output["case_id"] for event in events)

    actors = {event["actor"] for event in events}
    assert {"coordinator", "entity-agent", "order-shipment-agent", "payment-agent",
            "policy-agent", "verifier-agent"} <= actors


def test_gateway_calls_are_deduplicated_per_case(tmp_path: Path) -> None:
    """`get_order` is fetched once and reused by every specialist in the case."""
    payloads, failing = _payloads()
    _output, _, gateway = _solve(tmp_path, _case("unsupported_claim"), payloads, failing)

    tools = [name for name, _case_id, _args in gateway.calls]
    assert tools.count("get_order") == 1
    assert set(tools) == {
        "get_order",
        "get_customer_history",
        "get_order_items",
        "get_shipment_summary",
        "get_sellers",
        "get_product_context",
        "get_payment_timeline",
        "get_refund_timeline",
        "get_policy",
    }
    assert len(tools) == len(set(tools))


def test_claim_topic_defines_the_subject_of_the_dispute(tmp_path: Path) -> None:
    """The claim names the subject, and the specialist verdict follows it."""
    payloads, failing = _payloads(
        order=_order(delivered=ON_TIME_DELIVERED),
        shipment=_shipment(delivered=ON_TIME_DELIVERED),
        timeline=_timeline(
            payments=[_payment_row("credit_card", "1", "89.00")], events=[_capture("89.00")]
        ),
    )
    output, _, _ = _solve(tmp_path, _case("late_delivery_logistics"), payloads, failing)

    assert output["assessment"]["primary_issue"] == "late_delivery_logistics"
    assert output["assessment"]["case_status"] == "action_required"
    assert output["financial_resolution"]["recommended_refund_brl"] == 16.0
    assert output["shipment_analysis"]["verdict"] == "logistics_delay"


def test_unknown_claim_topic_falls_back_to_evidence(tmp_path: Path) -> None:
    """A claim that names no known issue keeps the historical evidence ordering."""
    payloads, failing = _payloads(
        order=_order(delivered=ON_TIME_DELIVERED),
        shipment=_shipment(delivered=ON_TIME_DELIVERED),
        timeline=_timeline(
            payments=[_payment_row("credit_card", "1", "89.00")], events=[_capture("89.00")]
        ),
    )
    output, _, _ = _solve(tmp_path, _case("document_request"), payloads, failing)

    assert output["assessment"]["primary_issue"] == "unsupported_claim"
    assert output["assessment"]["case_status"] == "no_action"
    assert output["financial_resolution"]["recommended_refund_brl"] == 0.0


def test_decoy_timestamps_never_change_the_conclusion(tmp_path: Path) -> None:
    """A stale `delivered_late` event / capture / refund must be ignored (§8)."""
    payloads, failing = _payloads(
        order=_order(delivered=ON_TIME_DELIVERED),
        shipment=_shipment(
            delivered=ON_TIME_DELIVERED,
            events=[_late_event("logistics_provider", at=DECOY_TS)],
        ),
        timeline=_timeline(
            payments=[_payment_row("credit_card", "1", "89.00")],
            events=[_capture("89.00"), _capture("16.00", at=DECOY_TS)],
        ),
        refund=_refund("failed", "16.00", at=DECOY_TS),
    )
    output, _, _ = _solve(tmp_path, _case("unsupported_claim"), payloads, failing)

    assert output["assessment"]["primary_issue"] == "unsupported_claim"
    assert output["shipment_analysis"]["verdict"] == "on_time"
    assert output["financial_resolution"]["recommended_refund_brl"] == 0.0


def test_late_delivery_logistics(tmp_path: Path) -> None:
    payloads, failing = _payloads(shipment=_shipment(events=[_late_event("logistics_provider")]))
    output, _, _ = _solve(tmp_path, _case("late_delivery_logistics"), payloads, failing)

    assert output["shipment_analysis"]["verdict"] == "logistics_delay"
    assert output["assessment"]["primary_issue"] == "late_delivery_logistics"
    assert output["assessment"]["case_status"] == "action_required"
    assert output["financial_resolution"]["recommended_refund_brl"] == 16.0
    assert output["root_cause_analysis"]["responsible_parties"] == [
        {"party_type": "logistics_provider", "party_id": None}
    ]
    assert output["resolution_actions"] == ["refund_freight"]


def test_late_delivery_seller(tmp_path: Path) -> None:
    payloads, failing = _payloads(shipment=_shipment(events=[_late_event("seller")]))
    output, _, _ = _solve(tmp_path, _case("late_delivery_seller"), payloads, failing)

    assert output["shipment_analysis"]["verdict"] == "seller_delay"
    assert output["assessment"]["primary_issue"] == "late_delivery_seller"
    assert output["financial_resolution"]["recommended_refund_brl"] == 18.0
    assert output["root_cause_analysis"]["responsible_parties"] == [
        {"party_type": "seller", "party_id": SELLER}
    ]


def test_canceled_order_paid(tmp_path: Path) -> None:
    payloads, failing = _payloads(
        order=_order(status="canceled", delivered=None),
        shipment=_shipment(status="canceled", delivered=None),
        timeline=_timeline(
            payments=[_payment_row("credit_card", "1", "79.00")], events=[_capture("79.00")]
        ),
    )
    output, _, _ = _solve(tmp_path, _case("canceled_order_paid"), payloads, failing)

    assert output["shipment_analysis"]["verdict"] == "returned"
    assert output["assessment"]["primary_issue"] == "canceled_order_paid"
    assert output["financial_resolution"]["recommended_refund_brl"] == 79.0
    assert output["resolution_actions"] == ["issue_refund"]


def test_unavailable_order_paid(tmp_path: Path) -> None:
    payloads, failing = _payloads(
        order=_order(status="unavailable", delivered=None),
        shipment=_shipment(status="unavailable", delivered=None),
        timeline=_timeline(
            payments=[_payment_row("credit_card", "1", "89.00")], events=[_capture("89.00")]
        ),
    )
    output, _, _ = _solve(tmp_path, _case("unavailable_order_paid"), payloads, failing)

    assert output["shipment_analysis"]["verdict"] == "lost"
    assert output["assessment"]["primary_issue"] == "unavailable_order_paid"
    assert output["financial_resolution"]["recommended_refund_brl"] == 89.0


def test_refund_failed(tmp_path: Path) -> None:
    payloads, failing = _payloads(
        order=_order(delivered=ON_TIME_DELIVERED),
        shipment=_shipment(delivered=ON_TIME_DELIVERED),
        timeline=_timeline(
            payments=[_payment_row("credit_card", "1", "52.00")], events=[_capture("52.00")]
        ),
        refund=_refund("failed", "52.00"),
    )
    output, _, _ = _solve(tmp_path, _case("refund_failed"), payloads, failing)

    assert output["payment_analysis"]["verdict"] == "refund_failed"
    assert output["assessment"]["primary_issue"] == "refund_failed"
    assert output["financial_resolution"]["recommended_refund_brl"] == 52.0
    assert output["resolution_actions"] == ["retry_refund"]
    assert output["assessment"]["confidence"] <= 0.85


def test_refund_pending(tmp_path: Path) -> None:
    payloads, failing = _payloads(
        order=_order(delivered=ON_TIME_DELIVERED),
        shipment=_shipment(delivered=ON_TIME_DELIVERED),
        timeline=_timeline(
            payments=[_payment_row("credit_card", "1", "89.00")], events=[_capture("89.00")]
        ),
        refund=_refund("pending", "89.00"),
    )
    output, _, _ = _solve(tmp_path, _case("refund_pending"), payloads, failing)

    assert output["payment_analysis"]["verdict"] == "refund_pending"
    assert output["assessment"]["primary_issue"] == "refund_pending"
    assert output["assessment"]["case_status"] == "needs_investigation"
    assert output["financial_resolution"]["recommended_refund_brl"] == 0.0
    assert output["resolution_actions"] == ["monitor_refund"]


def test_payment_mismatch(tmp_path: Path) -> None:
    payloads, failing = _payloads(
        order=_order(delivered=ON_TIME_DELIVERED),
        shipment=_shipment(delivered=ON_TIME_DELIVERED),
        timeline=_timeline(
            payments=[_payment_row("credit_card", "1", "35.00")],
            events=[_capture("35.00"), _capture("35.00", kind="reconciliation_mismatch")],
        ),
    )
    output, _, _ = _solve(tmp_path, _case("payment_mismatch"), payloads, failing)

    assert output["payment_analysis"]["verdict"] == "capture_mismatch"
    assert output["assessment"]["primary_issue"] == "payment_mismatch"
    assert output["financial_resolution"]["recommended_refund_brl"] == 35.0
    assert output["resolution_actions"] == ["reconcile_payment"]


def test_duplicate_charge(tmp_path: Path) -> None:
    payments = [
        _payment_row("credit_card", "1", "64.00"),
        _payment_row("voucher", "2", "64.00"),
        _payment_row("credit_card", "1", "64.00"),
        _payment_row("voucher", "2", "64.00"),
    ]
    payloads, failing = _payloads(
        order=_order(delivered=ON_TIME_DELIVERED),
        shipment=_shipment(delivered=ON_TIME_DELIVERED),
        timeline=_timeline(
            payments=payments,
            events=[_capture("64.00"), _capture("64.00", at="2018-08-05T11:00:00-03:00")],
        ),
    )
    output, _, _ = _solve(tmp_path, _case("duplicate_charge"), payloads, failing)

    assert output["payment_analysis"]["verdict"] == "duplicate_capture"
    assert output["assessment"]["primary_issue"] == "duplicate_charge"
    assert output["financial_resolution"]["recommended_refund_brl"] == 64.0
    assert output["resolution_actions"] == ["refund_duplicate_charge"]


def test_valid_split_payment(tmp_path: Path) -> None:
    payments = [
        _payment_row("credit_card", "1", "44.50"),
        _payment_row("voucher", "2", "44.50"),
    ]
    payloads, failing = _payloads(
        order=_order(delivered=ON_TIME_DELIVERED),
        shipment=_shipment(delivered=ON_TIME_DELIVERED),
        timeline=_timeline(
            payments=payments,
            events=[_capture("44.50"), _capture("44.50", at="2018-08-05T11:00:00-03:00")],
        ),
    )
    output, _, _ = _solve(tmp_path, _case("valid_split_payment"), payloads, failing)

    assert output["assessment"]["primary_issue"] == "valid_split_payment"
    assert output["assessment"]["case_status"] == "no_action"
    assert output["financial_resolution"]["recommended_refund_brl"] == 0.0
    assert output["resolution_actions"] == ["document_no_action"]


def test_temporal_helper_flags_decoy_rows(tmp_path: Path) -> None:
    del tmp_path
    from student_agent.temporal import is_consistent, order_anchors, pick_consistent

    anchors = order_anchors(_order())
    assert is_consistent(LIMIT, anchors)
    assert not is_consistent(DECOY_TS, anchors)
    assert not is_consistent(None, anchors)

    kept = pick_consistent(_items(), anchors)
    assert len(kept) == 1
    assert kept[0]["shipping_limit_date"] == LIMIT


def test_evidence_refs_are_gateway_refs(tmp_path: Path) -> None:
    payloads, failing = _payloads()
    output, _, _ = _solve(tmp_path, _case(), payloads, failing)

    refs = output["evidence_refs"]
    assert 1 <= len(refs) <= 30
    assert all(ref.startswith("ev_") for ref in refs)
    assert len(set(refs)) == len(refs)


def test_claim_topic_outranks_conflicting_evidence_as_primary(tmp_path: Path) -> None:
    """The claim names the subject; a different evidence signal stays secondary."""
    payloads, failing = _payloads(shipment=_shipment(events=[_late_event("seller")]))
    output, _, _ = _solve(tmp_path, _case("valid_split_payment"), payloads, failing)

    assert output["assessment"]["primary_issue"] == "valid_split_payment"
    assert "late_delivery_seller" in output["assessment"]["secondary_issues"]
    verdicts = {item["verdict"] for item in output["claim_assessments"]}
    assert "unsupported" in verdicts


def test_seller_party_id_matches_the_resolved_seller(tmp_path: Path) -> None:
    """A seller-facing verdict names the seller the evidence resolved, not the
    placeholder id carried by the public policy table."""
    payloads, failing = _payloads(shipment=_shipment(events=[_late_event("seller")]))
    output, _, _ = _solve(tmp_path, _case("late_delivery_seller"), payloads, failing)

    parties = output["root_cause_analysis"]["responsible_parties"]
    assert parties == [{"party_type": "seller", "party_id": SELLER}]
    assert SELLER in output["affected_entities"]["seller_ids"]
    assert output["financial_resolution"]["refund_lines"][0]["entity_id"] == SELLER


def test_second_history_version_supplies_the_timeline(tmp_path: Path) -> None:
    """When the history carries a second version with a different purchase date,
    the specialists reason over that version (the dispute is about it)."""
    payloads, failing = _payloads(
        order=_order(delivered=ON_TIME_DELIVERED),
        shipment=_shipment(
            delivered="2018-01-10T09:00:00-03:00",
            events=[_late_event("logistics_provider", at="2018-01-10T09:00:00-03:00")],
        ),
    )
    payloads["get_customer_history"] = _history(
        rows=[
            _order(delivered=ON_TIME_DELIVERED),
            {
                **_order(delivered="2018-01-10T09:00:00-03:00"),
                "order_purchase_timestamp": "2017-12-20T09:00:00-03:00",
                "order_estimated_delivery_date": "2018-01-05T09:00:00-03:00",
            },
        ]
    )
    output, _, _ = _solve(tmp_path, _case("late_delivery_logistics"), payloads, failing)

    assert output["shipment_analysis"]["verdict"] == "logistics_delay"
    assert output["assessment"]["primary_issue"] == "late_delivery_logistics"
    codes = {conflict["resolution_code"] for conflict in output["data_conflicts"]}
    assert "claimed_timeline_selected" in codes


def test_coincident_failed_refund_does_not_overwrite_a_valid_split(tmp_path: Path) -> None:
    """A stale failed refund next to a valid split must not change the verdict."""
    payments = [
        _payment_row("credit_card", "1", "52.00"),
        _payment_row("credit_card", "1", "44.50"),
        _payment_row("voucher", "2", "44.50"),
    ]
    payloads, failing = _payloads(
        order=_order(delivered=ON_TIME_DELIVERED),
        shipment=_shipment(delivered=ON_TIME_DELIVERED),
        timeline=_timeline(
            payments=payments,
            events=[
                _capture("52.00"),
                _capture("44.50"),
                _capture("44.50", at="2018-08-05T11:00:00-03:00"),
            ],
        ),
        refund=_refund("failed", "52.00"),
    )
    output, _, _ = _solve(tmp_path, _case("valid_split_payment"), payloads, failing)

    assert output["assessment"]["primary_issue"] == "valid_split_payment"
    assert output["payment_analysis"]["verdict"] == "reconciled"
    assert output["assessment"]["case_status"] == "no_action"
    assert output["financial_resolution"]["recommended_refund_brl"] == 0.0
