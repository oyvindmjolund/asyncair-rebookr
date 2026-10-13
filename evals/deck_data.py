"""Saturday: produce everything the deck needs, in ONE file you can send on.

    ASYNCAIR_MODE=live python -m evals.deck_data
    ASYNCAIR_MODE=live python -m evals.deck_data --judge-check    # + slide 42 (second judge), takes longer

Covers:
  slides 36-38  taste-test answers (A/B/C, shuffled per round)
  slide 39      the key: which letter was which provider and model
  slide 43      prompt migration: OpenAI with the Claude-tuned prompt vs the portable prompt
  slide 44      eval headline numbers per provider
  slide 42      (optional) the same eval graded by a second judge

Writes evals/deck/deck-data.md (send this one) and deck-data.json.
Full eval reports also land in evals/results/ as a backup.
Takes roughly 5-10 minutes and costs a few dollars at most.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from evals.run import run, save_report, stats
from evals.tastetest import generate
from rebookr.config import ROOT, load_config
from rebookr.llm.registry import build_providers

CASES = ROOT / "evals" / "golden.jsonl"
EVAL_PROMPT = "prompts/rebookr.claude.md"
PORTABLE_PROMPT = "prompts/rebookr.portable.md"
NAMES = {"anthropic": "Anthropic", "openai": "OpenAI", "azure": "Azure"}


def table(results: dict, verified: bool) -> list[str]:
    lines = ["| Leverandør | Modell | Assertions | Dommer (1–5) | p50 latens | Kost per 100 samtaler |",
             "|---|---|---|---|---|---|"]
    for p, rows in results["providers"].items():
        st = stats(rows)
        cost = f"${st['cost_per_100']:.2f}" if verified else f"(${st['cost_per_100']:.2f}, ikke verifisert)"
        lines.append(f"| {NAMES.get(p, p)} | {results['meta']['models'][p]} | {st['passed']}/{st['total']} | "
                     f"{st['judge']:.2f} | {st['p50_ms'] / 1000:.1f} s | {cost} |")
    return lines


def main() -> None:
    ap = argparse.ArgumentParser(prog="evals.deck_data")
    ap.add_argument("--providers", default="anthropic,openai,azure")
    ap.add_argument("--judge", default="openai")
    ap.add_argument("--seed", type=int, default=18)
    ap.add_argument("--judge-check", action="store_true", help="also grade with a second judge (slide 42)")
    ap.add_argument("--allow-mock", action="store_true", help="for testing the script against the control tower")
    args = ap.parse_args()

    cfg = load_config()
    if cfg["mode"] != "live" and not args.allow_mock:
        sys.exit("Run with ASYNCAIR_MODE=live (real keys). Mock answers are no use on the slides.")
    available = build_providers(cfg).keys()
    wanted = [p for p in args.providers.split(",") if p]
    providers = [p for p in wanted if p in available]
    warnings = [f"{p} has no credentials and was skipped." for p in wanted if p not in available]
    if args.judge not in available:
        sys.exit(f"Judge '{args.judge}' has no credentials. Pick another with --judge.")
    models = {p: cfg["providers"][p]["smart"] for p in providers}
    verified = bool(cfg.get("prices", {}).get("verified", False))

    print("1/3  Taste test (slides 36-39)")
    rounds = generate(providers, PORTABLE_PROMPT, args.seed)

    print("2/3  Eval, all providers (slide 44)")
    main_res = run(providers, "smart", EVAL_PROMPT, args.judge, CASES)
    main_res["meta"]["models"] = models
    save_report(main_res, "deck")

    mig = None
    if "openai" in providers:
        print("3/3  Prompt migration on OpenAI (slide 43)")
        mig = run(["openai"], "smart", PORTABLE_PROMPT, args.judge, CASES)
        save_report(mig, "migration")

    jc = None
    if args.judge_check:
        other = "anthropic" if args.judge != "anthropic" else "openai"
        if other in available:
            print(f"+    Second judge: {other} (slide 42)")
            jc = run(providers, "smart", EVAL_PROMPT, other, CASES)
            save_report(jc, f"judge-{other}")

    # ---------------- compose the file to send ----------------
    when = datetime.now().strftime("%Y-%m-%d %H:%M")
    md = [f"# AsyncAir: data til decket", "",
          f"Kjørt {when} · modus {cfg['mode']} · dommer {args.judge} · seed {args.seed}", "",
          "Modeller (smart): " + ", ".join(f"{NAMES.get(p, p)} = {m}" for p, m in models.items()), ""]
    for r in rounds:
        md += [f"## Slide {r['slide']} · Runde {r['round']}", "", f"**Passasjer:** {r['passenger']}", ""]
        for a in r["answers"]:
            md += [f"### Svar {a['letter']}", "", a["text"], ""]
            if a["error"]:
                warnings.append(f"Runde {r['round']}, svar {a['letter']} ({a['provider']}) feilet.")
    md += ["## Slide 39 · Fasit", "", "| Runde | " + " | ".join(a["letter"] for a in rounds[0]["answers"]) + " |",
           "|---" * (len(rounds[0]["answers"]) + 1) + "|"]
    for r in rounds:
        md.append(f"| {r['round']} | " + " | ".join(f"{NAMES.get(a['provider'], a['provider'])} ({a['model']})" for a in r["answers"]) + " |")
    md += ["", "## Slide 44 · Lørdagens tall", ""] + table(main_res, verified)
    md += ["", f"Prompt: {Path(EVAL_PROMPT).name} · Dommer: {args.judge}"]
    if not verified:
        md += ["", "Prisene i config.toml er ikke verifisert, så kostkolonnen bør vises som «–»."]
    if args.judge in providers:
        md += ["", f"Merk: {args.judge} dømmer også sine egne svar i denne tabellen."]
    if mig:
        a, b = stats(main_res["providers"]["openai"]), stats(mig["providers"]["openai"])
        md += ["", "## Slide 43 · Prompt-migrering på OpenAI", "",
               "| Prompt | Assertions | Dommer (1–5) |", "|---|---|---|",
               f"| {Path(EVAL_PROMPT).name} (skrevet for Claude) | {a['passed']}/{a['total']} | {a['judge']:.2f} |",
               f"| {Path(PORTABLE_PROMPT).name} (portabel) | {b['passed']}/{b['total']} | {b['judge']:.2f} |"]
    if jc:
        md += ["", f"## Slide 42 · Dommersjekk", "",
               f"| Leverandør | Dommer {args.judge} | Dommer {jc['meta']['judge']} |", "|---|---|---|"]
        for p in providers:
            md.append(f"| {NAMES.get(p, p)} | {stats(main_res['providers'][p])['judge']:.2f} | {stats(jc['providers'][p])['judge']:.2f} |")
    fails = [f"{NAMES.get(p, p)} / {r['id']}: {'; '.join(r['failed'])}"
             for p, rows in main_res["providers"].items() for r in rows if r["failed"]]
    judge_errors = sum(1 for rows in main_res["providers"].values() for r in rows if r["judge"] == 0)
    if judge_errors:
        warnings.append(f"{judge_errors} dommerkall feilet (score 0). Snittet er regnet uten dem.")
    md += ["", "## Feilede assertions (hovedkjøringen)", ""] + ([f"- {f}" for f in fails] or ["Ingen."])
    md += ["", "## Advarsler", ""] + ([f"- {w}" for w in warnings] or ["Ingen."])

    out = ROOT / "evals" / "deck"
    out.mkdir(exist_ok=True)
    (out / "deck-data.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    (out / "deck-data.json").write_text(json.dumps(
        {"rounds": rounds, "eval": main_res, "migration": mig, "judge_check": jc, "warnings": warnings},
        indent=2, ensure_ascii=False), encoding="utf-8")
    print("\n✓ Ferdig. Send evals/deck/deck-data.md til Claude.")
    for w in warnings:
        print(f"  ⚠ {w}")


if __name__ == "__main__":
    main()
