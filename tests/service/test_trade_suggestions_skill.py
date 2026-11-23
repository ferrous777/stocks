"""The trade-suggestions skill (.claude/skills/trade-suggestions) drives the MCP server; it must only name
tools and arguments the server actually exposes, and keep its safety rules."""
import pathlib
import re

import anyio

from stocks_service.mcp_server import build_mcp

SKILL = pathlib.Path(__file__).resolve().parents[2] / ".claude/skills/trade-suggestions/SKILL.md"


def _live_tools() -> dict:
    mcp = build_mcp(lambda: None)
    return {t.name: set(t.inputSchema.get("properties", {})) for t in anyio.run(mcp.list_tools)}


def test_skill_calls_only_live_tools_with_real_arguments():
    text = SKILL.read_text()
    tools = _live_tools()
    calls = re.findall(r"`([a-z_]+)\(([^`]*)\)`", text)
    assert calls, "the skill should name the tools it calls"
    for name, args in calls:
        assert name in tools, f"skill calls unknown MCP tool {name}"
        for kw in re.findall(r"([a-z_]+)=", args):
            assert kw in tools[name], f"{name} has no argument {kw}"


def test_skill_keeps_identity_and_safety_rules():
    text = " ".join(SKILL.read_text().split())                   # prose wraps across lines
    assert text.startswith('--- name: trade-suggestions ')
    for field in ("agent_id", "model_id", "prompt_version"):
        assert field in _live_tools()["get_outlook"] and f"`{field}" in text
    assert '"unknown"' in text                                   # never a guessed model id
    assert "Real accounts are never traded" in text
    assert 'account_id="paper-agent"' in text                     # paper orders only on the agent's account
    assert "Never confirm a watch-list change yourself" in text
    assert "HALT" in text and "placeable_until" in text
