"""Pre-flight check with REAL keys. Run from the repo root:

    ASYNCAIR_MODE=live python scripts/check_live.py

Checks every provider x alias for: plain text, tool calling, vision, streaming.
Token budgets are generous on purpose: reasoning models (e.g. gpt-5, gpt-5-mini)
spend part of the budget thinking and return an EMPTY answer if it runs out.
"""
import base64
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from rebookr.config import load_config  # noqa: E402
from rebookr.llm import ChatRequest, ImagePart, Message, TextDelta, TextPart  # noqa: E402
from rebookr.llm.registry import build_providers  # noqa: E402
from rebookr.tools import TOOLS  # noqa: E402

BUDGET = 1000
cfg = load_config()
if cfg["mode"] != "live":
    print("⚠ mode is not 'live' - set ASYNCAIR_MODE=live to test real APIs.")
providers = build_providers(cfg)
img = base64.b64encode((ROOT / "assets" / "boarding_pass.png").read_bytes()).decode()


def check_text(p, m):
    r = p.chat(ChatRequest([Message.user("Say OK.")], max_tokens=BUDGET), m)
    if not r.text:
        raise RuntimeError("empty answer (token budget used up by reasoning?)")
    return True


def check_tools(p, m):
    r = p.chat(ChatRequest([Message.user("Find flights from KRS to OSL.")], tools=TOOLS, max_tokens=BUDGET), m)
    if not r.tool_calls:
        raise RuntimeError(f"no tool call, model replied: {r.text[:50]!r}")
    return r.tool_calls[0].name == "search_flights"


def check_vision(p, m):
    req = ChatRequest([Message("user", [ImagePart("image/png", img), TextPart("What is the flight number? Answer briefly.")])],
                      max_tokens=BUDGET)
    r = p.chat(req, m)
    if not r.text:
        raise RuntimeError("empty answer (token budget used up by reasoning?)")
    return "512" in r.text


def check_stream(p, m):
    events = list(p.stream(ChatRequest([Message.user("Count to five.")], max_tokens=BUDGET), m))
    if not any(isinstance(e, TextDelta) for e in events):
        raise RuntimeError("no text streamed (token budget used up by reasoning?)")
    return True


CHECKS = {"text": check_text, "tools": check_tools, "vision": check_vision, "stream": check_stream}

ok_all = True
for name, provider in providers.items():
    for alias in ("fast", "smart"):
        model = cfg["providers"][name][alias]
        row = []
        for check, fn in CHECKS.items():
            try:
                ok = fn(provider, model)
                ok_all &= ok
                row.append(f"{check} {'✓' if ok else '✗'}")
            except Exception as e:
                ok_all = False
                row.append(f"{check} ✗ ({type(e).__name__}: {str(e)[:70]})")
        print(f"{name:<10} {alias:<6} {model:<22} " + "  ".join(row))

print("\nAll good ✈" if ok_all else
      "\nSomething failed. Note: a 'fast' model that sometimes asks back instead of calling a tool is model "
      "behaviour, not a bug - Rebookr routes rebooking to 'smart'.")
