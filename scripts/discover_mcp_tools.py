"""Dev helper: in danh sach MCP tool kem inputSchema.

`day09 mcp-tools` chi in ten tool, trong khi de viet agent dung can biet dung ten
tham so. Script nay dung cung mot ket noi (team API key trong .env) de doc
`inputSchema` va luu ket qua vao `traces/mcp_tools.json`.

Day khong phai phan cua pipeline: chi la buoc discovery mot lan truoc khi code.
Chay:  .venv\\Scripts\\python.exe scripts\\discover_mcp_tools.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from student_agent.config import Settings  # noqa: E402


async def main() -> None:
    settings = Settings.load(ROOT)
    headers = {"Authorization": f"Bearer {settings.team_api_key}"}
    timeout = httpx2.Timeout(60.0, connect=30.0)
    async with (
        httpx2.AsyncClient(headers=headers, timeout=timeout) as http_client,
        streamable_http_client(settings.mcp_endpoint, http_client=http_client) as (
            read_stream,
            write_stream,
        ),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()
        response = await session.list_tools()
        dump: list[dict[str, object]] = []
        for tool in response.tools:
            schema = tool.input_schema or {}
            entry = {
                "name": tool.name,
                "description": (tool.description or "").strip(),
                "required": schema.get("required", []),
                "properties": schema.get("properties", {}),
            }
            dump.append(entry)
            print(f"* {tool.name}")
            print(f"  required: {entry['required']}")
            print(f"  properties: {json.dumps(entry['properties'], ensure_ascii=False)}")
        out_path = ROOT / "traces" / "mcp_tools.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(dump, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nOK: {len(dump)} tool -> {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
