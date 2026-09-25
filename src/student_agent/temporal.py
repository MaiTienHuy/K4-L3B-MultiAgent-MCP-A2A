"""Shared temporal helpers for the L3B specialist agents.

MCP evidence for one order mixes two sources for the same ``order_id``:

* the **authoritative** source, whose timestamps line up with ``get_order``
  (the row the gateway documents as authoritative), and
* a **stale / decoy** source whose timestamps sit months away from the order
  timeline (this is the planted "source conflict" the task asks us to resolve).

Every specialist agent therefore needs the same primitive: given a candidate
timestamp, decide whether it is consistent with the order row. Keeping that in
one place avoids the shipment agent and the payment agent disagreeing about the
same evidence.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

# A candidate row is considered authoritative when it sits within this many days
# of at least one timestamp of the authoritative order row. Observed real data:
# consistent rows are 0-4 days away, every decoy row is >= 15 days away.
TOLERANCE_DAYS = 10

ORDER_TIMESTAMP_FIELDS = (
    "order_purchase_timestamp",
    "order_approved_at",
    "order_delivered_carrier_date",
    "order_delivered_customer_date",
    "order_estimated_delivery_date",
)

# Fields that carry a timestamp in shipment / payment / refund payloads.
CANDIDATE_TIMESTAMP_FIELDS = (
    "shipping_limit_date",
    "shipping_limit_at",
    "event_at",
    "timestamp",
    "created_at",
)

# Window used when no order anchor can be used (missing order row). Anchored on
# the purchase timestamp because every generated case opens with a purchase.
FALLBACK_WINDOW_DAYS = 20


def parse_ts(value: Any) -> datetime | None:
    """Parse an ISO-8601 timestamp; return ``None`` for missing/invalid input."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def day_distance(left: datetime, right: datetime) -> float:
    """Absolute distance between two timestamps, expressed in days."""
    return abs((left - right).total_seconds()) / 86400.0


def order_anchors(order_data: dict[str, Any] | None) -> list[datetime]:
    """All usable timestamps of the authoritative order row."""
    if not isinstance(order_data, dict):
        return []
    anchors: list[datetime] = []
    for field_name in ORDER_TIMESTAMP_FIELDS:
        parsed = parse_ts(order_data.get(field_name))
        if parsed is not None:
            anchors.append(parsed)
    return anchors


def anchor_distance(value: Any, anchors: list[datetime]) -> float | None:
    """Smallest distance (days) between ``value`` and any order anchor."""
    parsed = parse_ts(value)
    if parsed is None or not anchors:
        return None
    return min(day_distance(parsed, anchor) for anchor in anchors)


def is_consistent(
    value: Any, anchors: list[datetime], tolerance_days: int = TOLERANCE_DAYS
) -> bool:
    """True when a candidate timestamp belongs to the authoritative source."""
    distance = anchor_distance(value, anchors)
    if distance is None:
        return False
    return distance <= tolerance_days


def candidate_timestamp(entry: dict[str, Any]) -> Any:
    """First timestamp-like value found on a shipment/payment/refund entry."""
    for field_name in CANDIDATE_TIMESTAMP_FIELDS:
        if field_name in entry:
            return entry[field_name]
    return None


def pick_consistent(
    entries: list[dict[str, Any]],
    anchors: list[datetime],
    tolerance_days: int = TOLERANCE_DAYS,
) -> list[dict[str, Any]]:
    """Keep the entries consistent with the authoritative order timeline.

    Falls back to the full list only when the payload carries no timestamp at
    all, so that evidence is never silently dropped.
    """
    if not entries:
        return []
    if not anchors:
        return list(entries)
    timestamped = [entry for entry in entries if candidate_timestamp(entry) is not None]
    if not timestamped:
        return list(entries)
    consistent = [
        entry for entry in timestamped if is_consistent(candidate_timestamp(entry), anchors, tolerance_days)
    ]
    return consistent


def as_float(value: Any) -> float | None:
    """Parse BRL amounts that the gateway returns as strings."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def round2(value: float | None) -> float | None:
    return None if value is None else round(value, 2)
