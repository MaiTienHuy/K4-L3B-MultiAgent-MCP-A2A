from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_repository_contains_no_competition_payload() -> None:
    """Guarantee that the released starter repo ships no competition payload.

    On a working fork the inputs/outputs are downloaded locally (and are
    gitignored), so the guarantee cannot hold there and the check is skipped
    instead of failing a legitimate working copy.
    """
    if (ROOT / "case-set.json").exists():
        pytest.skip("local fork: competition inputs/outputs are present (gitignored)")
    assert not (ROOT / "case-set.json").exists()
    assert list((ROOT / "inputs").glob("*.json")) == []
    assert list((ROOT / "outputs").glob("*.json")) == []
    forbidden = {"oracles", "reference-outputs", "private-partitions.json", "mcp-access.json"}
    assert not any(path.name in forbidden for path in ROOT.rglob("*"))


def test_example_environment_has_no_real_key() -> None:
    content = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "sk-team-replace_me" in content
    assert content.count("sk-team-") == 1
