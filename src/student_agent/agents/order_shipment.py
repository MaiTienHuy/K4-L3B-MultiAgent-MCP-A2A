"""Order, Product & Shipment Agent --- Trinh Xuan Huy phu trach.

Implements:
  - OrderShipmentResult dataclass (supports both attribute access for workflow.py and dict access)
  - order_shipment.run(case, entity_result, gateway, trace) called by workflow.py
  - run_order_shipment_agent(...) helper for standalone/unit test execution
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ..mcp_gateway import EvidenceGateway
from ..trace import TraceWriter

ACTOR_NAME = "order-shipment-agent"
ALLOWED_TOOLS = frozenset(
    {
        "get_order",
        "get_order_items",
        "get_shipment_summary",
        "get_sellers",
        "get_product_context",
    }
)


def _parse_iso(ts: Any) -> datetime | None:
    if not isinstance(ts, str) or not ts.strip():
        return None
    try:
        return datetime.fromisoformat(ts.strip().replace("Z", "+00:00"))
    except ValueError:
        return None


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
class OrderShipmentResult:
    """Output contract for Order/Shipment Agent.

    Compatible with both attribute access (`result.verdict`, `result.evidence_refs`)
    used in `workflow.py` and dictionary key access (`result["order_data"]`, `result["conflicts"]`).
    """

    verdict: str = "insufficient_evidence"
    late_seller_ids: list[str] = field(default_factory=list)
    timeline_complete: bool = False
    order_data: dict[str, Any] = field(
        default_factory=lambda: {
            "orders": {},
            "items": [],
            "products": [],
            "sellers": [],
            "total_price_brl": 0.0,
            "total_freight_brl": 0.0,
        }
    )
    shipment_timeline: dict[str, Any] = field(
        default_factory=lambda: {
            "shipments_by_order": {},
            "timeline_complete": False,
            "late_seller_ids": [],
            "events": [],
        }
    )
    delivery_status: dict[str, Any] = field(
        default_factory=lambda: {
            "verdict": "insufficient_evidence",
            "order_status_summary": "unknown",
        }
    )
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    order_ids: list[str] = field(default_factory=list)
    item_ids: list[str] = field(default_factory=list)
    seller_ids: list[str] = field(default_factory=list)
    shipment_ids: list[str] = field(default_factory=list)

    @property
    def data_conflicts(self) -> list[dict[str, Any]]:
        return self.conflicts

    @property
    def shipment_analysis(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "late_seller_ids": self.late_seller_ids[:20],
            "timeline_complete": self.timeline_complete,
        }

    @property
    def extracted_entities(self) -> dict[str, list[str]]:
        return {
            "order_ids": self.order_ids[:20],
            "item_ids": self.item_ids[:20],
            "seller_ids": self.seller_ids[:20],
            "shipment_ids": self.shipment_ids[:20],
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "late_seller_ids": self.late_seller_ids,
            "timeline_complete": self.timeline_complete,
            "order_data": self.order_data,
            "shipment_timeline": self.shipment_timeline,
            "delivery_status": self.delivery_status,
            "shipment_analysis": self.shipment_analysis,
            "extracted_entities": self.extracted_entities,
            "conflicts": self.conflicts,
            "data_conflicts": self.conflicts,
            "evidence_refs": self.evidence_refs,
            "order_ids": self.order_ids,
            "item_ids": self.item_ids,
            "seller_ids": self.seller_ids,
            "shipment_ids": self.shipment_ids,
        }

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.to_dict().get(key, default)

    def keys(self):
        return self.to_dict().keys()

    def __contains__(self, key: object) -> bool:
        return key in self.to_dict()


class OrderShipmentAgent:
    """Specialist Agent for Order, Item, Product, Seller, and Shipment Timeline Analysis."""

    def __init__(self, gateway: Any, trace: TraceWriter) -> None:
        self._gateway = gateway
        self._trace = trace
        self._cache: dict[tuple[str, str, tuple[tuple[str, str], ...]], dict[str, Any]] = {}

    async def _call_tool(
        self, tool_name: str, *, case_id: str, **arguments: str
    ) -> dict[str, Any] | None:
        if tool_name not in ALLOWED_TOOLS:
            raise PermissionError(f"{ACTOR_NAME} is not permitted to call tool {tool_name!r}")
        cache_key = (case_id, tool_name, tuple(sorted(arguments.items())))
        if cache_key in self._cache:
            return self._cache[cache_key]

        try:
            evidence = await self._gateway.call(tool_name, case_id=case_id, **arguments)
        except Exception:
            return None

        if not isinstance(evidence, dict):
            return None

        self._cache[cache_key] = evidence
        ev_ref = evidence.get("evidence_ref")
        if isinstance(ev_ref, str) and ev_ref:
            self._trace.emit(
                case_id=case_id,
                event_type="tool_result_consumed",
                actor=ACTOR_NAME,
                tool_name=tool_name,
                evidence_refs=[ev_ref],
            )
        return evidence

    async def investigate(
        self,
        case: dict[str, Any],
        *,
        entity_result: Any = None,
        entity_id: str | None = None,
        resolved_order_ids: list[str] | None = None,
    ) -> OrderShipmentResult:
        case_id = str(case["case_id"])

        self._trace.emit(
            case_id=case_id,
            event_type="task_assigned",
            actor="coordinator",
            target=ACTOR_NAME,
        )

        # 1. Normalize target order_ids from entity_result / entity_id / resolved_order_ids
        order_ids: list[str] = []
        if resolved_order_ids:
            order_ids.extend(oid for oid in resolved_order_ids if isinstance(oid, str) and oid)
        if isinstance(entity_id, str) and entity_id:
            order_ids.append(entity_id)

        if entity_result is not None:
            if isinstance(entity_result, str) and entity_result:
                order_ids.append(entity_result)
            elif isinstance(entity_result, dict):
                for key in ("resolved_order_ids", "order_ids"):
                    vals = entity_result.get(key)
                    if isinstance(vals, list):
                        order_ids.extend(str(v) for v in vals if v)
                if entity_result.get("entity_id"):
                    order_ids.append(str(entity_result["entity_id"]))
            else:
                for attr in ("resolved_order_ids", "order_ids"):
                    vals = getattr(entity_result, attr, None)
                    if isinstance(vals, list):
                        order_ids.extend(str(v) for v in vals if v)
                ent_id = getattr(entity_result, "entity_id", None)
                if isinstance(ent_id, str) and ent_id:
                    order_ids.append(ent_id)

        entity_status = (
            entity_result.get("status")
            if isinstance(entity_result, dict)
            else getattr(entity_result, "status", None)
        )
        if not order_ids and entity_status != "not_found":
            claimed = (
                case.get("customer_request", {}).get("claimed_order_id")
                if isinstance(case.get("customer_request"), dict)
                else None
            )
            if isinstance(claimed, str) and claimed:
                order_ids.append(claimed)

        order_ids = _unique_preserve_order(order_ids)

        if not order_ids:
            empty_res = OrderShipmentResult()
            self._trace.emit(
                case_id=case_id,
                event_type="handoff",
                actor=ACTOR_NAME,
                target="policy-agent",
                decision_code="insufficient_evidence",
            )
            return empty_res

        include_product = bool(
            case.get("investigation_scope", {}).get("include_product_context", True)
        )

        orders_by_id: dict[str, dict[str, Any]] = {}
        all_items: list[dict[str, Any]] = []
        all_products: list[dict[str, Any]] = []
        all_sellers: list[dict[str, Any]] = []
        shipments_by_order: dict[str, dict[str, Any]] = {}
        evidence_refs: list[str] = []

        for oid in order_ids:
            order_ev = await self._call_tool("get_order", case_id=case_id, order_id=oid)
            if order_ev and order_ev.get("evidence_ref"):
                evidence_refs.append(order_ev["evidence_ref"])
                if isinstance(order_ev.get("data"), dict) and order_ev["data"]:
                    orders_by_id[oid] = order_ev["data"]

            tasks = [
                self._call_tool("get_order_items", case_id=case_id, order_id=oid),
                self._call_tool("get_shipment_summary", case_id=case_id, order_id=oid),
                self._call_tool("get_sellers", case_id=case_id, order_id=oid),
            ]
            if include_product:
                tasks.append(self._call_tool("get_product_context", case_id=case_id, order_id=oid))

            results = await asyncio.gather(*tasks)
            items_ev, ship_ev, sellers_ev = results[0], results[1], results[2]
            prod_ev = results[3] if include_product and len(results) > 3 else None

            if items_ev and items_ev.get("evidence_ref"):
                evidence_refs.append(items_ev["evidence_ref"])
                if isinstance(items_ev.get("data"), list):
                    all_items.extend(row for row in items_ev["data"] if isinstance(row, dict))

            if ship_ev and ship_ev.get("evidence_ref"):
                evidence_refs.append(ship_ev["evidence_ref"])
                if isinstance(ship_ev.get("data"), dict) and ship_ev["data"]:
                    shipments_by_order[oid] = ship_ev["data"]

            if sellers_ev and sellers_ev.get("evidence_ref"):
                evidence_refs.append(sellers_ev["evidence_ref"])
                if isinstance(sellers_ev.get("data"), list):
                    all_sellers.extend(row for row in sellers_ev["data"] if isinstance(row, dict))

            if prod_ev and prod_ev.get("evidence_ref"):
                evidence_refs.append(prod_ev["evidence_ref"])
                if isinstance(prod_ev.get("data"), list):
                    all_products.extend(
                        row for row in prod_ev["data"] if isinstance(row, dict)
                    )

        # 2. Extract affected entities & propagate back to entity_result if mutable
        extracted_item_ids = _unique_preserve_order(
            [str(item.get("order_item_id")) for item in all_items if item.get("order_item_id")]
        )
        extracted_seller_ids = _unique_preserve_order(
            [str(item.get("seller_id")) for item in all_items if item.get("seller_id")]
            + [str(s.get("seller_id")) for s in all_sellers if s.get("seller_id")]
        )
        extracted_shipment_ids: list[str] = []
        for oid, sdata in shipments_by_order.items():
            if sdata.get("shipment_id"):
                extracted_shipment_ids.append(str(sdata["shipment_id"]))
        extracted_shipment_ids = _unique_preserve_order(extracted_shipment_ids)

        if entity_result is not None and not isinstance(entity_result, (str, dict)):
            if hasattr(entity_result, "item_ids"):
                entity_result.item_ids = _unique_preserve_order(
                    list(getattr(entity_result, "item_ids", [])) + extracted_item_ids
                )
            if hasattr(entity_result, "seller_ids"):
                entity_result.seller_ids = _unique_preserve_order(
                    list(getattr(entity_result, "seller_ids", [])) + extracted_seller_ids
                )
            if hasattr(entity_result, "shipment_ids"):
                entity_result.shipment_ids = _unique_preserve_order(
                    list(getattr(entity_result, "shipment_ids", [])) + extracted_shipment_ids
                )

        # 3. Compute canonical item price & freight totals
        total_price_brl, total_freight_brl = _compute_clean_order_totals(
            orders_by_id=orders_by_id, all_items=all_items
        )

        # 4. Analyze timeline, delivery status, late sellers, and data conflicts
        analysis = _analyze_order_and_shipment(
            order_ids=order_ids,
            orders_by_id=orders_by_id,
            all_items=all_items,
            shipments_by_order=shipments_by_order,
        )

        evidence_refs = _unique_preserve_order(evidence_refs, max_items=30)

        result = OrderShipmentResult(
            verdict=analysis["verdict"],
            late_seller_ids=analysis["late_seller_ids"],
            timeline_complete=analysis["timeline_complete"],
            order_data={
                "orders": orders_by_id,
                "items": all_items,
                "products": all_products,
                "sellers": all_sellers,
                "total_price_brl": total_price_brl,
                "total_freight_brl": total_freight_brl,
            },
            shipment_timeline={
                "shipments_by_order": shipments_by_order,
                "timeline_complete": analysis["timeline_complete"],
                "late_seller_ids": analysis["late_seller_ids"],
                "events": analysis["all_events"],
            },
            delivery_status={
                "verdict": analysis["verdict"],
                "order_status_summary": analysis["order_status_summary"],
            },
            conflicts=analysis["conflicts"],
            evidence_refs=evidence_refs,
            order_ids=order_ids,
            item_ids=extracted_item_ids,
            seller_ids=extracted_seller_ids,
            shipment_ids=extracted_shipment_ids,
        )

        self._trace.emit(
            case_id=case_id,
            event_type="handoff",
            actor=ACTOR_NAME,
            target="policy-agent",
            decision_code=result.verdict,
            evidence_refs=evidence_refs[:20] or None,
        )
        return result


def _compute_clean_order_totals(
    *,
    orders_by_id: dict[str, dict[str, Any]],
    all_items: list[dict[str, Any]],
) -> tuple[float, float]:
    """Sum item price and freight_value, filtering out corrupted duplicate item rows."""
    seen_item_keys: dict[tuple[str, str], dict[str, Any]] = {}
    for row in all_items:
        oid = str(row.get("order_id") or "")
        iid = str(row.get("order_item_id") or "")
        if not iid:
            continue
        purchase_dt = _parse_iso(orders_by_id.get(oid, {}).get("order_purchase_timestamp"))
        limit_dt = _parse_iso(row.get("shipping_limit_date"))
        key = (oid, iid)
        if key not in seen_item_keys:
            seen_item_keys[key] = row
        else:
            if purchase_dt and limit_dt and limit_dt >= purchase_dt:
                seen_item_keys[key] = row

    total_price = 0.0
    total_freight = 0.0
    for row in seen_item_keys.values():
        try:
            total_price += float(row.get("price") or 0.0)
        except (TypeError, ValueError):
            pass
        try:
            total_freight += float(row.get("freight_value") or 0.0)
        except (TypeError, ValueError):
            pass
    return round(total_price, 2), round(total_freight, 2)


def _analyze_order_and_shipment(
    *,
    order_ids: list[str],
    orders_by_id: dict[str, dict[str, Any]],
    all_items: list[dict[str, Any]],
    shipments_by_order: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    conflicts: list[dict[str, Any]] = []
    late_sellers: list[str] = []
    all_timelines_complete = True
    verdicts: list[str] = []
    order_statuses: list[str] = []
    all_events: list[dict[str, Any]] = []

    items_by_id: dict[str, list[dict[str, Any]]] = {}
    for row in all_items:
        iid = str(row.get("order_item_id") or "")
        if iid:
            items_by_id.setdefault(iid, []).append(row)
    for iid, rows in items_by_id.items():
        if len(rows) > 1:
            limits = {
                str(r.get("shipping_limit_date"))
                for r in rows
                if r.get("shipping_limit_date")
            }
            if len(limits) > 1:
                conflicts.append(
                    {
                        "field": "shipping_limit_date",
                        "sources": ["item", "shipment"],
                        "selected_source": "shipment",
                        "resolution_code": "FILTER_POST_PURCHASE_SHIPPING_LIMIT",
                    }
                )

    for oid in order_ids:
        order_row = orders_by_id.get(oid, {})
        ship_row = shipments_by_order.get(oid, {})
        if not order_row and not ship_row:
            all_timelines_complete = False
            verdicts.append("insufficient_evidence")
            continue

        o_status = str(order_row.get("order_status") or ship_row.get("order_status") or "unknown")
        order_statuses.append(o_status)

        purchase_dt = _parse_iso(order_row.get("order_purchase_timestamp"))
        approved_dt = _parse_iso(order_row.get("order_approved_at"))
        carrier_dt = _parse_iso(
            ship_row.get("delivered_carrier_at") or order_row.get("order_delivered_carrier_date")
        )
        customer_dt = _parse_iso(
            ship_row.get("delivered_customer_at")
            or order_row.get("order_delivered_customer_date")
        )
        estimated_dt = _parse_iso(
            ship_row.get("estimated_delivery_at")
            or order_row.get("order_estimated_delivery_date")
        )

        if not all([purchase_dt, approved_dt, carrier_dt, customer_dt, estimated_dt]):
            all_timelines_complete = False

        if (
            order_row.get("order_status")
            and ship_row.get("order_status")
            and order_row["order_status"] != ship_row["order_status"]
        ):
            conflicts.append(
                {
                    "field": "order_status",
                    "sources": ["order", "shipment"],
                    "selected_source": "shipment",
                    "resolution_code": "AUTHORITATIVE_SHIPMENT_STATUS",
                }
            )

        if o_status in ("canceled", "unavailable") and customer_dt is not None:
            conflicts.append(
                {
                    "field": "delivery_status",
                    "sources": ["order", "shipment"],
                    "selected_source": "order",
                    "resolution_code": "CANCELED_ORDER_STATUS_CONFLICT",
                }
            )

        shipping_limits = ship_row.get("shipping_limits")
        if not isinstance(shipping_limits, list) or not shipping_limits:
            shipping_limits = [
                {
                    "order_item_id": r.get("order_item_id"),
                    "seller_id": r.get("seller_id"),
                    "shipping_limit_at": r.get("shipping_limit_date"),
                }
                for r in all_items
                if r.get("order_id") == oid
            ]

        valid_limits: list[tuple[str, datetime]] = []
        for lim in shipping_limits:
            if not isinstance(lim, dict):
                continue
            lim_dt = _parse_iso(lim.get("shipping_limit_at") or lim.get("shipping_limit_date"))
            seller_id = str(lim.get("seller_id") or "")
            if lim_dt and seller_id:
                if purchase_dt and lim_dt < purchase_dt:
                    continue
                valid_limits.append((seller_id, lim_dt))

        timestamp_seller_late = False
        for seller_id, lim_dt in valid_limits:
            if carrier_dt and carrier_dt > lim_dt:
                late_sellers.append(seller_id)
                timestamp_seller_late = True

        timestamp_logistics_late = bool(
            customer_dt and estimated_dt and customer_dt > estimated_dt
        )

        events = ship_row.get("events") if isinstance(ship_row.get("events"), list) else []
        confirmed_events = [
            e
            for e in events
            if isinstance(e, dict) and str(e.get("status", "confirmed")) == "confirmed"
        ]
        all_events.extend(confirmed_events)

        event_verdict: str | None = None
        for ev in confirmed_events:
            ev_type = str(ev.get("event_type") or "").lower()
            ev_actor = str(ev.get("actor") or "").lower()

            if "lost" in ev_type:
                event_verdict = "lost"
                break
            if "return" in ev_type:
                event_verdict = "returned"
                break
            if "seller" in ev_type or (
                ev_actor == "seller" and ("late" in ev_type or "delay" in ev_type)
            ):
                event_verdict = "seller_delay"
                for seller_id, _ in valid_limits:
                    late_sellers.append(seller_id)
                if not valid_limits:
                    for item in all_items:
                        if item.get("order_id") == oid and item.get("seller_id"):
                            late_sellers.append(str(item["seller_id"]))
                break
            if ev_type in ("delivered_late", "logistics_delay") or (
                ev_actor == "logistics_provider" and ("late" in ev_type or "delay" in ev_type)
            ):
                event_verdict = "logistics_delay"
                break
            if "on_time" in ev_type or ev_type == "delivered_on_time":
                event_verdict = "on_time"

        if (
            event_verdict == "logistics_delay"
            and not timestamp_logistics_late
            and customer_dt
            and estimated_dt
        ):
            conflicts.append(
                {
                    "field": "delivered_customer_date",
                    "sources": ["order", "shipment"],
                    "selected_source": "shipment",
                    "resolution_code": "AUTHORITATIVE_SHIPMENT_EVENT",
                }
            )
        elif event_verdict == "seller_delay" and not timestamp_seller_late and carrier_dt:
            conflicts.append(
                {
                    "field": "delivered_carrier_date",
                    "sources": ["order", "shipment"],
                    "selected_source": "shipment",
                    "resolution_code": "AUTHORITATIVE_SHIPMENT_EVENT",
                }
            )
        elif event_verdict == "on_time" and (timestamp_logistics_late or timestamp_seller_late):
            conflicts.append(
                {
                    "field": "delivery_timeline",
                    "sources": ["order", "shipment"],
                    "selected_source": "shipment",
                    "resolution_code": "AUTHORITATIVE_SHIPMENT_EVENT",
                }
            )

        if event_verdict is not None:
            verdicts.append(event_verdict)
        elif o_status in ("canceled", "unavailable") and customer_dt is not None:
            verdicts.append("conflicting")
        elif timestamp_seller_late:
            verdicts.append("seller_delay")
        elif timestamp_logistics_late:
            verdicts.append("logistics_delay")
        elif customer_dt is not None and estimated_dt is not None and customer_dt <= estimated_dt:
            verdicts.append("on_time")
        else:
            verdicts.append("insufficient_evidence")

    priority = [
        "conflicting",
        "lost",
        "returned",
        "seller_delay",
        "logistics_delay",
        "on_time",
        "insufficient_evidence",
    ]
    final_verdict = "insufficient_evidence"
    for p in priority:
        if p in verdicts:
            final_verdict = p
            break

    unique_conflicts: list[dict[str, Any]] = []
    seen_conflict_fields: set[tuple[str, str]] = set()
    for c in conflicts:
        key = (c["field"], c["resolution_code"])
        if key not in seen_conflict_fields:
            seen_conflict_fields.add(key)
            unique_conflicts.append(c)
            if len(unique_conflicts) >= 5:
                break

    return {
        "verdict": final_verdict,
        "late_seller_ids": _unique_preserve_order(late_sellers),
        "timeline_complete": all_timelines_complete,
        "order_status_summary": order_statuses[0] if order_statuses else "unknown",
        "conflicts": unique_conflicts,
        "all_events": all_events,
    }


async def run(
    case: dict[str, Any],
    entity_result: Any,
    gateway: Any,
    trace: TraceWriter,
) -> OrderShipmentResult:
    """Entrypoint called by Mai Tien Huy's coordinator in `workflow.py`."""
    agent = OrderShipmentAgent(gateway, trace)
    return await agent.investigate(case, entity_result=entity_result)


async def run_order_shipment_agent(
    case: dict[str, Any],
    gateway: Any,
    trace: TraceWriter,
    *,
    entity_result: Any = None,
    entity_id: str | None = None,
    resolved_order_ids: list[str] | None = None,
) -> OrderShipmentResult:
    """Flexible entrypoint for standalone or unit-test invocation."""
    agent = OrderShipmentAgent(gateway, trace)
    return await agent.investigate(
        case,
        entity_result=entity_result,
        entity_id=entity_id,
        resolved_order_ids=resolved_order_ids,
    )

