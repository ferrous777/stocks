"""The trade-suggestions skill (.claude/skills/trade-suggestions) drives the MCP server; it must only name
tools and arguments the server actually exposes, keep the user's authority rules, and state server facts
(time exit) that match the code."""
import datetime as dt
import pathlib
import re

import anyio

from stocks_service import sessions
from stocks_service.mcp_server import build_mcp
from stocks_service.sim.execution import ExecutionPolicy

SKILL_DIR = pathlib.Path(__file__).resolve().parents[2] / ".claude/skills/trade-suggestions"
SKILL = SKILL_DIR / "SKILL.md"
DOCS = sorted(SKILL_DIR.rglob("*.md"))


def _flat(p: pathlib.Path) -> str:
    return " ".join(p.read_text().split())                     # prose wraps across lines


def _live_tools() -> dict:
    mcp = build_mcp(lambda: None)
    return {t.name: set(t.inputSchema.get("properties", {})) for t in anyio.run(mcp.list_tools)}


def test_skill_files_call_only_live_tools_with_real_arguments():
    tools = _live_tools()
    seen = 0
    for doc in DOCS:
        for name, args in re.findall(r"`([a-z_]+)\(([^`]*)\)`", doc.read_text()):
            seen += 1
            assert name in tools, f"{doc.name} calls unknown MCP tool {name}"
            for kw in re.findall(r"([a-z_]+)=", args):
                assert kw in tools[name], f"{doc.name}: {name} has no argument {kw}"
    assert seen >= 5, "the skill should name the tools it calls"


def test_referenced_files_exist():
    for doc in DOCS:
        for rel in re.findall(r"\]\(((?:references|scripts)/[^)]+)\)", doc.read_text()):
            assert (SKILL_DIR / rel).exists(), f"{doc.name} links missing {rel}"
    assert (SKILL_DIR / "scripts/paper_limits.py").exists()


def test_skill_keeps_identity_and_authority_rules():
    text = _flat(SKILL)
    assert text.startswith("--- name: trade-suggestions ")
    assert "`trade-suggestions-v2`" in text and "`2026-11-21-paper-v2`" in text
    for field in ("agent_id", "model_id", "prompt_version"):
        assert field in _live_tools()["get_outlook"]
    guide = _flat(SKILL_DIR / "references/execution-guide.md")
    assert '`model_id`: the exact model ID if the runtime states it, otherwise `"unknown"`' in guide
    assert "**Never:** place real orders" in text and "loosen an existing stop" in text
    assert "`paper-agent` only" in text and "`paper-baseline`" in text   # baseline is never operated
    assert "confirm a watch-list change on the user's behalf" in text
    assert "PAPER EXPERIMENT — unvalidated; not a real-money recommendation." in text
    assert "At most **120 words**" in text and "at most **two** new positions" in text
    assert "`paper-agent:<SYMBOL>:<side>:<outlook run_id>:<target session>`" in text
    assert 'min_grade="insufficient"' in text


def test_time_exit_facts_match_the_execution_policy():
    assert ExecutionPolicy().timeout_sessions == 126
    guide = _flat(SKILL_DIR / "references/execution-guide.md")
    assert "`timeout_sessions = 126`" in guide and "nth_session_after(fill_session, 127)" in guide
    fill = dt.date(2026, 11, 23)
    assert sessions.nth_session_after(fill, 127) == dt.date(2027, 5, 27)   # the dated observation in the guide
    assert "2027-05-27" in guide
