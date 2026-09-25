"""Order / Product / Shipment Agent -- STUB tam thoi.

File nay thuoc quyen so huu cua **Trinh Xuan Huy** (KE_HOACH_MILESTONE.md §11).
LVH chi tao stub de package `student_agent.agents` import duoc (neu khong,
moi lenh `day09` deu loi `ModuleNotFoundError`) va de kiem thu tich hop
`workflow._build_output` voi `EntityResult` cua minh.

Tool duoc cap (discovery that): get_order, get_order_items, get_shipment_summary,
get_sellers, get_product_context.

TXH hay thay the toan bo noi dung file nay.
"""

from __future__ import annotations

from typing import Any

from ..mcp_gateway import EvidenceGateway
from ..trace import TraceWriter

_MESSAGE = (
    "order_shipment.run chua duoc trien khai (Trinh Xuan Huy). Tool duoc cap: "
    "get_order, get_order_items, get_shipment_summary, get_sellers, get_product_context."
)


async def run(
    case: dict[str, Any], entity_result: Any, gateway: EvidenceGateway, trace: TraceWriter
) -> Any:
    del case, entity_result, gateway, trace
    raise NotImplementedError(_MESSAGE)
