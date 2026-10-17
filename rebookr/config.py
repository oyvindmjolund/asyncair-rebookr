"""Loads config.toml (+ env overrides)."""
from __future__ import annotations

import os
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCAL = ROOT / ".asyncair.toml"   # written by `python -m rebookr join`, git-ignored


def load_config(path: str | os.PathLike | None = None) -> dict:
    path = Path(path or os.environ.get("ASYNCAIR_CONFIG", ROOT / "config.toml"))
    with open(path, "rb") as f:
        cfg = tomllib.load(f)
    local = {}
    if LOCAL.is_file():
        with open(LOCAL, "rb") as f:
            local = tomllib.load(f)
    # Precedence: environment > .asyncair.toml (join) > config.toml
    cfg["mode"] = os.environ.get("ASYNCAIR_MODE", cfg.get("mode", "mock"))
    cfg["team"] = os.environ.get("ASYNCAIR_TEAM", local.get("team", cfg.get("team", "anonymous")))
    cfg.setdefault("mock", {})["url"] = os.environ.get(
        "MOCK_URL", local.get("mock_url", cfg["mock"].get("url", "http://localhost:8787"))).rstrip("/")
    return cfg


def read_prompt(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")
