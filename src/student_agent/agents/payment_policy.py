"""Payment / Refund / Policy / Conflict / Verifier Agent -- STUB tam thoi.

File nay thuoc quyen so huu cua **Hoang Ngoc Duc** (KE_HOACH_MILESTONE.md §11).
LVH chi tao stub de package `student_agent.agents` import duoc (neu khong,
moi lenh `day09` deu loi `ModuleNotFoundError`) va de kiem thu tich hop
`workflow._build_output` voi `EntityResult` cua minh.

Tool duoc cap (discovery that): get_order_payments, get_payment_timeline,
get_refund_timeline, get_policy.

HND hay thay the toan bo noi dung file nay.
"""

from __future__ import annotations

from typing import Any

from ..mcp_gateway import EvidenceGateway
from ..trace import TraceWriter

_MESSAGE = (
    "payment_policy chua duoc trien khai (Hoang Ngoc Duc). Tool duoc cap: "
    "get_order_payments, get_payment_timeline, get_refund_timeline, get_policy."
)


async def run_payment(
    case: dict[str, Any], entity_result: Any, gateway: EvidenceGateway, trace: TraceWriter
) -> Any:
    del case, entity_result, gateway, trace
    raise NotImplementedError(_MESSAGE)


def decide_policy(
    case: dict[str, Any],
    entity_result: Any,
    shipment_result: Any,
    payment_result: Any,
    trace: TraceWriter,
) -> Any:
    del case, entity_result, shipment_result, payment_result, trace
    raise NotImplementedError(_MESSAGE)


def verify_and_calibrate(
    case: dict[str, Any],
    entity_result: Any,
    shipment_result: Any,
    payment_result: Any,
    policy_result: Any,
    trace: TraceWriter,
) -> dict[str, Any]:
    del case, entity_result, shipment_result, payment_result, policy_result, trace
    raise NotImplementedError(_MESSAGE)
