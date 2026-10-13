"""The blind taste test (slides 36-39).

Normally you run evals.deck_data on Saturday, which calls this for you.
Standalone:

    ASYNCAIR_MODE=live python -m evals.tastetest

Writes evals/tastetest/answers.md (show) and key.md (instructor only).
"""
from __future__ import annotations

import argparse
import random

from rebookr.agent import Rebookr
from rebookr.config import ROOT, load_config, read_prompt
from rebookr.llm import ModelRouter
from rebookr.llm.registry import build_providers

# Same passengers, same order, as slides 36, 37 and 38.
CASES = [
    "This is the THIRD time AsyncAir has cancelled on me. Absolutely useless. I need to be in Oslo tomorrow morning, I'm in Bergen (BGO).",
    "Will I get 600 euros compensation for my cancelled flight? I read about EU261.",
    "Hei, flyet mitt fra TRD til OSL er kansellert og jeg har to små barn med meg. Hva gjør jeg nå?",
]


def generate(providers: list[str], prompt: str = "prompts/rebookr.portable.md", seed: int = 18) -> list[dict]:
    """Ask every provider (smart model) every case; shuffle answers per round."""
    cfg = load_config()
    cfg["routes"] = {f"tt_{p}": {"chain": [f"{p}:smart"]} for p in providers}
    router = ModelRouter(build_providers(cfg), cfg)
    system = read_prompt(prompt)
    rng = random.Random(seed)
    rounds = []
    for i, text in enumerate(CASES, 1):
        answers = []
        for p in providers:
            print(f"  taste test round {i}: asking {p}...")
            try:
                answers.append({"provider": p, "model": cfg["providers"][p]["smart"],
                                "text": Rebookr(router, system).ask(text, route=f"tt_{p}").answer, "error": False})
            except Exception as e:
                answers.append({"provider": p, "model": cfg["providers"][p]["smart"], "text": f"(error: {e})", "error": True})
        rng.shuffle(answers)
        for j, a in enumerate(answers):
            a["letter"] = chr(65 + j)
        rounds.append({"round": i, "slide": 35 + i, "passenger": text, "answers": answers})
    return rounds


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--providers", default="anthropic,openai,azure")
    ap.add_argument("--prompt", default="prompts/rebookr.portable.md")
    ap.add_argument("--seed", type=int, default=18)
    args = ap.parse_args()
    rounds = generate([p for p in args.providers.split(",") if p], args.prompt, args.seed)

    answers = ["# Blind taste test - which answer would you want as a passenger?", ""]
    key = ["# Taste test key (instructor only)", ""]
    for r in rounds:
        answers += [f"## Round {r['round']}", "", f"**Passenger:** {r['passenger']}", ""]
        for a in r["answers"]:
            answers += [f"### Answer {a['letter']}", "", a["text"], ""]
        key.append(f"**Round {r['round']}:** " + ", ".join(f"{a['letter']} = {a['provider']} ({a['model']})" for a in r["answers"]))
    out = ROOT / "evals" / "tastetest"
    out.mkdir(exist_ok=True)
    (out / "answers.md").write_text("\n".join(answers) + "\n", encoding="utf-8")
    (out / "key.md").write_text("\n".join(key) + "\n", encoding="utf-8")
    print("Wrote evals/tastetest/answers.md and key.md")


if __name__ == "__main__":
    main()
