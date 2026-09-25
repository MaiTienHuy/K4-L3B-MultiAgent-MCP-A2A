"""Dev helper: goi thu mot MCP tool va in payload that de biet cau truc `data`.

Dung chinh `EvidenceGateway` cua repo nen dong thoi kiem tra gateway/contract.
Moi lan goi deu duoc server audit theo team + case, nen chi goi khi can thiet.

Vi du:
  .venv\\Scripts\\python.exe scripts\\probe_mcp_payload.py get_order \
      --case-id L3B_CASE_001 order_id=<hex32>
  .venv\\Scripts\\python.exe scripts\\probe_mcp_payload.py get_customer_history \
      --case-id L3B_CASE_001 customer_unique_id=customer-xxxxxxxxxxxx
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from student_agent.config import Settings  # noqa: E402
from student_agent.contracts import Contracts  # noqa: E402
from student_agent.mcp_gateway import connect_gateway  # noqa: E402


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe one MCP tool and print its payload.")
    parser.add_argument("tool_name")
    parser.add_argument("arguments", nargs="*", help="key=value pairs passed to the tool")
    parser.add_argument("--case-id", default="L3B_CASE_001")
    return parser.parse_args()


async def main() -> None:
    args = _parse_args()
    arguments = {}
    for item in args.arguments:
        if "=" not in item:
            raise SystemExit(f"argument must be key=value: {item!r}")
        key, value = item.split("=", 1)
        arguments[key] = value

    settings = Settings.load(ROOT)
    contracts = Contracts(ROOT / "contracts" / "schemas")
    async with connect_gateway(settings.mcp_endpoint, settings.team_api_key, contracts) as gateway:
        evidence = await gateway.call(args.tool_name, case_id=args.case_id, **arguments)

    print(json.dumps(evidence, indent=2, ensure_ascii=False)[:4000])
    out_dir = ROOT / "traces"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"mcp_probe_{args.tool_name}.json"
    out_path.write_text(json.dumps(evidence, indent=2, ensure_ascii=False), encoding="utf-8")
    data = evidence.get("data")
    if isinstance(data, dict):
        print(f"\nTOP-LEVEL data keys: {sorted(data)}")
        for key, value in data.items():
            if isinstance(value, list) and value and isinstance(value[0], dict):
                print(f"  {key}: list[{len(value)}] item keys={sorted(value[0])}")
            elif isinstance(value, dict):
                print(f"  {key}: dict keys={sorted(value)}")
    print(f"\nOK: saved -> {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
