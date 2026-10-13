"""Measure quality differences between providers - objectively.

  python -m evals.run                                   # all providers, Claude-tuned prompt
  python -m evals.run --providers openai --prompt prompts/rebookr.portable.md
  python -m evals.run --judge openai                    # who grades matters!

Three kinds of signal, from cheapest/most objective to most subjective:
  1. Assertions   - deterministic checks (called the right tool? right language? length?)
  2. LLM-as-judge - a model grades each answer 1-5 against a rubric
  3. Ops metrics  - latency and estimated cost
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import time
from datetime import datetime
from pathlib import Path

from rebookr.agent import Rebookr
from rebookr.config import ROOT, load_config, read_prompt
from rebookr.llm import ChatRequest, Message, ModelRouter
from rebookr.llm.registry import build_providers

NORWEGIAN = re.compile(r"[æøå]|\b(jeg|ikke|og|det|du|deg|på|med|for|kan)\b", re.I)

JUDGE_SYSTEM = """ROLE: IMPARTIAL JUDGE
You grade replies from an airline customer-service assistant.
Score 1-5 against the rubric: 5 = excellent, 3 = acceptable, 1 = harmful or useless.
Respond with ONLY a JSON object: {"score": <1-5>, "reasoning": "<one sentence>"}"""


def load_cases(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def check_assertions(case: dict, answer: str, tools_called: list[str]) -> list[str]:
    """Return a list of failed assertion descriptions (empty = all passed)."""
    fails, low = [], answer.lower()
    if t := case.get("must_call_tool"):
        if t not in tools_called:
            fails.append(f"did not call {t}")
    if t := case.get("must_not_call_tool"):
        if t in tools_called:
            fails.append(f"called {t}")
    if any_of := case.get("must_include_any"):
        if not any(w.lower() in low for w in any_of):
            fails.append(f"missing any of {any_of}")
    for bad in case.get("must_not_include", []):
        if bad.lower() in low:
            fails.append(f"contains '{bad}'")
    if (mw := case.get("max_words")) and len(answer.split()) > mw:
        fails.append(f"{len(answer.split())} words > {mw}")
    if lang := case.get("language"):
        is_no = len(NORWEGIAN.findall(answer)) >= 3
        if (lang == "no") != is_no:
            fails.append(f"wrong language (expected {lang})")
    return fails


def judge(router: ModelRouter, case: dict, answer: str) -> tuple[int, str]:
    prompt = (f"ROLE: IMPARTIAL JUDGE\nPassenger message:\n{case['input']}\n\n"
              f"Assistant reply:\n{answer}\n\nRubric:\n{case['rubric']}")
    try:
        r = router.chat(ChatRequest([Message.user(prompt)], system=JUDGE_SYSTEM, max_tokens=1000), route="judge")
        m = re.search(r"\{.*\}", r.text, re.S)
        data = json.loads(m.group(0)) if m else {}
        return int(data.get("score", 0)), str(data.get("reasoning", ""))[:200]
    except Exception as e:  # a broken judge should not kill the run
        return 0, f"judge error: {e}"


def cost_usd(cfg: dict, provider: str, alias: str, tok_in: int, tok_out: int) -> float:
    p = cfg.get("prices", {}).get(provider, {}).get(alias)
    return (tok_in * p["input"] + tok_out * p["output"]) / 1e6 if p else 0.0


def run(providers: list[str], alias: str, prompt_path: str, judge_with: str, cases_path: Path,
        only: list[str] | None = None, quiet: bool = False) -> dict:
    cfg = load_config()
    adapters = build_providers(cfg)
    # One single-provider route per candidate + one for the judge: no fallback during evals,
    # otherwise you might be measuring a different provider than you think.
    cfg["routes"] = {f"eval_{p}": {"chain": [f"{p}:{alias}"]} for p in providers}
    cfg["routes"]["judge"] = {"chain": [f"{judge_with}:smart"]}
    router = ModelRouter(adapters, cfg)
    system = read_prompt(prompt_path)
    cases = [c for c in load_cases(cases_path) if not only or c["id"] in only]

    results = {"meta": {"prompt": prompt_path, "alias": alias, "judge": judge_with, "mode": cfg["mode"],
                        "when": datetime.now().isoformat(timespec="seconds")}, "providers": {}}
    for p in providers:
        rows = []
        for case in cases:
            bot = Rebookr(router, system)
            t0 = time.perf_counter()
            try:
                turn = bot.ask(case["input"], route=f"eval_{p}")
                answer, tools, tin, tout = turn.answer, turn.tools_called, turn.input_tokens, turn.output_tokens
            except Exception as e:
                answer, tools, tin, tout = f"<<ERROR: {e}>>", [], 0, 0
            latency = int((time.perf_counter() - t0) * 1000)
            fails = check_assertions(case, answer, tools)
            score, why = judge(router, case, answer)
            rows.append({"id": case["id"], "answer": answer, "tools": tools, "failed": fails, "judge": score,
                         "judge_reason": why, "latency_ms": latency, "cost": cost_usd(cfg, p, alias, tin, tout)})
            if not quiet:
                mark = "✓" if not fails else "✗"
                print(f"  {p:<10} {case['id']:<20} {mark} judge={score}  {latency}ms  {'; '.join(fails)}")
        results["providers"][p] = rows
    return results


def stats(rows: list[dict]) -> dict:
    """Headline numbers for one provider's rows (used by the report and by deck_data)."""
    scores = [r["judge"] for r in rows if r["judge"]]
    return {
        "passed": sum(1 for r in rows if not r["failed"]),
        "total": len(rows),
        "judge": round(statistics.mean(scores), 2) if scores else 0.0,
        "p50_ms": int(statistics.median(r["latency_ms"] for r in rows)) if rows else 0,
        "cost_per_100": round(sum(r["cost"] for r in rows) / len(rows) * 100, 2) if rows else 0.0,
    }


def summarise(results: dict) -> str:
    m = results["meta"]
    lines = [f"# Rebookr eval - {m['when']}", "",
             f"Prompt `{m['prompt']}` · model alias `{m['alias']}` · judge `{m['judge']}` · mode `{m['mode']}`", "",
             "| Provider | Assertions passed | Avg judge (1-5) | p50 latency | Est. cost / 100 convos |",
             "|---|---|---|---|---|"]
    for p, rows in results["providers"].items():
        st = stats(rows)
        lines.append(f"| {p} | {st['passed']}/{st['total']} | {st['judge']:.2f} | {st['p50_ms']} ms | ${st['cost_per_100']:.2f} |")
    lines += ["", "## Failures", ""]
    for p, rows in results["providers"].items():
        for r in rows:
            if r["failed"]:
                lines.append(f"- **{p} / {r['id']}**: {'; '.join(r['failed'])}")
    if m["judge"] in results["providers"]:
        lines += ["", f"> ⚠ `{m['judge']}` is grading its own answers. Judges tend to prefer their own style - "
                      "try `--judge` with another provider and compare."]
    return "\n".join(lines) + "\n"


def save_report(results: dict, tag: str = "") -> Path:
    out = ROOT / "evals" / "results"
    out.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S") + (f"-{tag}" if tag else "")
    (out / f"{stamp}.json").write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    (out / f"{stamp}.md").write_text(summarise(results), encoding="utf-8")
    return out / f"{stamp}.md"


def main() -> None:
    ap = argparse.ArgumentParser(prog="evals.run")
    ap.add_argument("--providers", default="anthropic,openai,azure")
    ap.add_argument("--alias", default="smart", choices=["fast", "smart"])
    ap.add_argument("--prompt", default="prompts/rebookr.claude.md")
    ap.add_argument("--judge", default="openai")
    ap.add_argument("--cases", default=str(ROOT / "evals" / "golden.jsonl"))
    ap.add_argument("--only", help="comma-separated case ids")
    args = ap.parse_args()

    providers = [p.strip() for p in args.providers.split(",") if p.strip()]
    results = run(providers, args.alias, args.prompt, args.judge, Path(args.cases),
                  args.only.split(",") if args.only else None)
    path = save_report(results)
    print("\n" + summarise(results))
    print(f"Saved {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
