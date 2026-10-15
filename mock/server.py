"""AsyncAir control tower: a mock LLM server.

Speaks three wire formats so the *real* vendor SDKs can talk to it:
  Anthropic  POST /anthropic/v1/messages
  OpenAI     POST /openai/v1/chat/completions
  Azure      POST /azure/openai/deployments/<deployment>/chat/completions?api-version=...

Blind test voting (slides 35-39):
  GET  /vote                  phone page with A/B/C buttons
  GET  /results               projector page with live results
  POST /_vote/control         {"active": 1|2|3|0}  or  {"reset": true}

Chaos control (the red button):
  GET  /                      dashboard with buttons + team scoreboard
  GET  /_chaos                current state as JSON
  POST /_chaos  {"provider": "anthropic", "mode": "down"}
       modes: ok | down | slow | ratelimit       provider "all" resets everything

Run:  python -m mock.server   (port 8787, override with MOCK_PORT)
Stdlib only, so it starts even if pip is having a bad day.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from mock.brain import Decision, Turn, decide, estimate_tokens

PROVIDERS = ("anthropic", "openai", "azure")
MODES = ("ok", "down", "slow", "ratelimit", "flaky")   # flaky = dies halfway through a stream
SLOW_SECONDS = float(os.environ.get("MOCK_SLOW_SECONDS", "8"))
STREAM_DELAY = float(os.environ.get("MOCK_STREAM_DELAY", "0.03"))

_lock = threading.Lock()
STATE = {p: "ok" for p in PROVIDERS}
COUNTS = {p: {"ok": 0, "failed": 0} for p in PROVIDERS}
TEAMS: dict[str, dict] = {}
DASHBOARD = (Path(__file__).parent / "dashboard.html").read_text(encoding="utf-8")
VOTE_PAGE = (Path(__file__).parent / "vote.html").read_text(encoding="utf-8")
RESULTS_PAGE = (Path(__file__).parent / "results.html").read_text(encoding="utf-8")

# Blind test voting. One ballot per voter per round; voters may change their mind until the round closes.
ROUNDS = ("1", "2", "3")
VOTE = {"active": "0", "ballots": {r: {} for r in ROUNDS}, "seen": {}}
ONLINE_WINDOW = 12  # seconds since a phone last polled


def _vote_snapshot(include_counts: bool) -> dict:
    now = time.time()
    online = sum(1 for t in VOTE["seen"].values() if now - t < ONLINE_WINDOW)
    snap = {"active": VOTE["active"], "online": online,
            "totals": {r: len(VOTE["ballots"][r]) for r in ROUNDS}}
    if include_counts:
        snap["counts"] = {r: {c: sum(1 for v in VOTE["ballots"][r].values() if v == c) for c in "ABC"} for r in ROUNDS}
    return snap


def _record(provider: str, team: str, ok: bool) -> None:
    with _lock:
        COUNTS[provider]["ok" if ok else "failed"] += 1
        t = TEAMS.setdefault(team, {"ok": 0, "failed": 0, "last_provider": "-", "last_seen": 0.0})
        t["ok" if ok else "failed"] += 1
        if ok:
            t["last_provider"] = provider
        t["last_seen"] = time.time()


# --------------------------------------------------------------------------
# Request normalisation: vendor format -> list[Turn]
# --------------------------------------------------------------------------

def _anthropic_turns(body: dict) -> tuple[str, list[Turn], list[str]]:
    system = body.get("system") or ""
    if isinstance(system, list):
        system = " ".join(b.get("text", "") for b in system)
    turns = []
    for m in body.get("messages", []):
        t = Turn(m["role"])
        content = m["content"]
        if isinstance(content, str):
            t.text = content
        else:
            for b in content:
                if b["type"] == "text":
                    t.text += b["text"]
                elif b["type"] == "image":
                    t.has_image = True
                elif b["type"] == "tool_result":
                    c = b.get("content", "")
                    if isinstance(c, list):
                        c = "".join(x.get("text", "") for x in c)
                    t.tool_results.append(c)
                elif b["type"] == "tool_use":
                    t.tool_calls.append(b["name"])
        turns.append(t)
    tools = [t["name"] for t in body.get("tools", [])]
    return system, turns, tools


def _openai_turns(body: dict) -> tuple[str, list[Turn], list[str]]:
    system, turns = "", []
    for m in body.get("messages", []):
        role = m["role"]
        content = m.get("content")
        if role in ("system", "developer"):
            system += content if isinstance(content, str) else "".join(p.get("text", "") for p in content)
            continue
        if role == "tool":
            # OpenAI sends each tool result as its own message; fold into a user turn.
            if turns and turns[-1].role == "user" and turns[-1].tool_results:
                turns[-1].tool_results.append(content)
            else:
                turns.append(Turn("user", tool_results=[content]))
            continue
        t = Turn(role)
        if isinstance(content, str):
            t.text = content
        elif isinstance(content, list):
            for p in content:
                if p.get("type") == "text":
                    t.text += p["text"]
                elif p.get("type") == "image_url":
                    t.has_image = True
        for tc in m.get("tool_calls") or []:
            t.tool_calls.append(tc["function"]["name"])
        turns.append(t)
    tools = [t["function"]["name"] for t in body.get("tools", [])]
    return system, turns, tools


# --------------------------------------------------------------------------
# Response rendering
# --------------------------------------------------------------------------

def _chunks(text: str, size: int = 12):
    for i in range(0, len(text), size):
        yield text[i:i + size]


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "AsyncAirMock/1.0"

    def log_message(self, fmt, *args):  # quieter logs
        if os.environ.get("MOCK_VERBOSE"):
            super().log_message(fmt, *args)

    # ---- helpers -------------------------------------------------------
    def _json(self, status: int, payload, headers: dict | None = None):
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _sse_start(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

    def _sse(self, data: str, event: str | None = None):
        out = (f"event: {event}\n" if event else "") + f"data: {data}\n\n"
        self.wfile.write(out.encode())
        self.wfile.flush()

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length", "0") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def _html(self, page: str):
        data = page.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _team(self) -> str:
        return (self.headers.get("x-asyncair-team") or "anonymous")[:40]

    # ---- chaos ----------------------------------------------------------
    def _chaos_gate(self, provider: str) -> bool:
        """Return True if the request may proceed; otherwise send an error."""
        mode = STATE[provider]
        if mode == "flaky":
            return True          # fails later, mid-stream (non-streaming requests succeed)
        if mode == "slow":
            time.sleep(SLOW_SECONDS)
            return True
        if mode == "ok":
            return True
        _record(provider, self._team(), ok=False)
        if provider == "anthropic":
            if mode == "down":
                self._json(529, {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}})
            else:
                self._json(429, {"type": "error", "error": {"type": "rate_limit_error", "message": "Rate limit exceeded (mock)"}}, {"retry-after": "20"})
        else:
            if mode == "down":
                self._json(503, {"error": {"message": "The server is overloaded or not ready yet. (mock)", "type": "server_error", "param": None, "code": None}})
            else:
                self._json(429, {"error": {"message": "Rate limit reached (mock)", "type": "requests", "param": None, "code": "rate_limit_exceeded"}}, {"retry-after": "20"})
        return False

    # ---- routing ----------------------------------------------------------
    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/dashboard"):
            self._html(DASHBOARD)
        elif path == "/vote":
            self._html(VOTE_PAGE)
        elif path == "/results":
            self._html(RESULTS_PAGE)
        elif path == "/_vote/state":
            voter = (parse_qs(urlparse(self.path).query).get("voter") or [""])[0][:64]
            with _lock:
                if voter:
                    VOTE["seen"][voter] = time.time()
                snap = _vote_snapshot(include_counts=False)
                snap["mine"] = {r: VOTE["ballots"][r].get(voter) for r in ROUNDS} if voter else {}
            self._json(200, snap)
        elif path == "/_vote/results":
            with _lock:
                self._json(200, _vote_snapshot(include_counts=True))
        elif path == "/_chaos":
            with _lock:
                self._json(200, {"state": STATE, "counts": COUNTS, "teams": TEAMS})
        elif path == "/health":
            self._json(200, {"ok": True})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            body = self._body()
        except json.JSONDecodeError:
            return self._json(400, {"error": "invalid json"})

        if path == "/_chaos":
            return self._set_chaos(body)
        if path == "/_vote":
            return self._cast_vote(body)
        if path == "/_vote/control":
            with _lock:
                if body.get("reset"):
                    VOTE["ballots"] = {r: {} for r in ROUNDS}
                    VOTE["active"] = "0"
                elif str(body.get("active")) in ("0",) + ROUNDS:
                    VOTE["active"] = str(body.get("active"))
                else:
                    return self._json(400, {"error": "send {'active': 0-3} or {'reset': true}"})
                print(f"[control tower] voting -> round {VOTE['active']}", flush=True)
                return self._json(200, _vote_snapshot(include_counts=False))
        if path == "/_reset_scores":
            with _lock:
                TEAMS.clear()
                for c in COUNTS.values():
                    c.update(ok=0, failed=0)
            return self._json(200, {"ok": True})
        if path.endswith("/v1/messages") and path.startswith("/anthropic"):
            return self._anthropic(body)
        if path.startswith("/openai") and path.endswith("/chat/completions"):
            return self._openai(body, "openai")
        if path.startswith("/azure") and path.endswith("/chat/completions"):
            m = re.search(r"/deployments/([^/]+)/", path)
            if m:
                body.setdefault("model", m.group(1))
            return self._openai(body, "azure")
        self._json(404, {"error": f"unknown route {path}"})

    def _cast_vote(self, body: dict):
        voter = str(body.get("voter", ""))[:64]
        rnd, choice = str(body.get("round", "")), str(body.get("choice", ""))
        if not voter or choice not in ("A", "B", "C"):
            return self._json(400, {"error": "bad vote"})
        with _lock:
            if rnd != VOTE["active"]:
                return self._json(409, {"error": "closed", "active": VOTE["active"]})
            VOTE["ballots"][rnd][voter] = choice
            VOTE["seen"][voter] = time.time()
        self._json(200, {"ok": True, "round": rnd, "choice": choice})

    def _set_chaos(self, body: dict):
        provider, mode = body.get("provider"), body.get("mode", "ok")
        if mode not in MODES:
            return self._json(400, {"error": f"mode must be one of {MODES}"})
        with _lock:
            targets = PROVIDERS if provider == "all" else (provider,)
            for p in targets:
                if p not in STATE:
                    return self._json(400, {"error": f"unknown provider {p}"})
                STATE[p] = mode
        print(f"[control tower] {provider} -> {mode}", flush=True)
        self._json(200, {"state": STATE})

    # ---- Anthropic Messages API ----------------------------------------------
    def _anthropic(self, body: dict):
        if "max_tokens" not in body:
            return self._json(400, {"type": "error", "error": {"type": "invalid_request_error", "message": "max_tokens: Field required"}})
        if not self._chaos_gate("anthropic"):
            return
        system, turns, tools = _anthropic_turns(body)
        d = decide("anthropic", system, turns, tools)
        model = body.get("model", "claude-mock")
        in_tok = estimate_tokens(json.dumps(body))
        out_text = d.text if d.kind == "text" else json.dumps(d.tool_args)
        out_tok = estimate_tokens(out_text)
        msg_id = f"msg_mock_{uuid.uuid4().hex[:16]}"
        _record("anthropic", self._team(), ok=True)

        if d.kind == "tool":
            block = {"type": "tool_use", "id": f"toolu_mock_{uuid.uuid4().hex[:12]}", "name": d.tool_name, "input": d.tool_args}
            stop = "tool_use"
        else:
            block = {"type": "text", "text": d.text}
            stop = "end_turn"

        if not body.get("stream"):
            return self._json(200, {
                "id": msg_id, "type": "message", "role": "assistant", "model": model,
                "content": [block], "stop_reason": stop, "stop_sequence": None,
                "usage": {"input_tokens": in_tok, "output_tokens": out_tok},
            })

        self._sse_start()
        start = {"id": msg_id, "type": "message", "role": "assistant", "model": model, "content": [],
                 "stop_reason": None, "stop_sequence": None, "usage": {"input_tokens": in_tok, "output_tokens": 1}}
        self._sse(json.dumps({"type": "message_start", "message": start}), "message_start")
        if d.kind == "tool":
            self._sse(json.dumps({"type": "content_block_start", "index": 0,
                                  "content_block": {"type": "tool_use", "id": block["id"], "name": d.tool_name, "input": {}}}), "content_block_start")
            for piece in _chunks(json.dumps(d.tool_args), 16):
                self._sse(json.dumps({"type": "content_block_delta", "index": 0, "delta": {"type": "input_json_delta", "partial_json": piece}}), "content_block_delta")
                time.sleep(STREAM_DELAY)
        else:
            self._sse(json.dumps({"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}), "content_block_start")
            pieces = list(_chunks(d.text))
            for i, piece in enumerate(pieces):
                if STATE["anthropic"] == "flaky" and i == len(pieces) // 2:
                    # Anthropic really does send errors as SSE events mid-stream.
                    self._sse(json.dumps({"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}}), "error")
                    return
                self._sse(json.dumps({"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": piece}}), "content_block_delta")
                time.sleep(STREAM_DELAY)
        self._sse(json.dumps({"type": "content_block_stop", "index": 0}), "content_block_stop")
        self._sse(json.dumps({"type": "message_delta", "delta": {"stop_reason": stop, "stop_sequence": None}, "usage": {"output_tokens": out_tok}}), "message_delta")
        self._sse(json.dumps({"type": "message_stop"}), "message_stop")

    # ---- OpenAI / Azure Chat Completions --------------------------------------
    def _openai(self, body: dict, provider: str):
        if not self._chaos_gate(provider):
            return
        system, turns, tools = _openai_turns(body)
        d = decide(provider, system, turns, tools)
        model = body.get("model", "gpt-mock")
        in_tok = estimate_tokens(json.dumps(body))
        out_tok = estimate_tokens(d.text if d.kind == "text" else json.dumps(d.tool_args))
        cid = f"chatcmpl-mock{uuid.uuid4().hex[:12]}"
        created = int(time.time())
        _record(provider, self._team(), ok=True)
        call_id = f"call_mock_{uuid.uuid4().hex[:12]}"

        if not body.get("stream"):
            if d.kind == "tool":
                message = {"role": "assistant", "content": None, "tool_calls": [
                    {"id": call_id, "type": "function", "function": {"name": d.tool_name, "arguments": json.dumps(d.tool_args)}}]}
                finish = "tool_calls"
            else:
                message = {"role": "assistant", "content": d.text}
                finish = "stop"
            return self._json(200, {
                "id": cid, "object": "chat.completion", "created": created, "model": model,
                "choices": [{"index": 0, "message": message, "finish_reason": finish}],
                "usage": {"prompt_tokens": in_tok, "completion_tokens": out_tok, "total_tokens": in_tok + out_tok},
            })

        self._sse_start()

        def chunk(delta: dict, finish=None):
            return json.dumps({"id": cid, "object": "chat.completion.chunk", "created": created, "model": model,
                               "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]})

        if d.kind == "tool":
            self._sse(chunk({"role": "assistant", "content": None, "tool_calls": [
                {"index": 0, "id": call_id, "type": "function", "function": {"name": d.tool_name, "arguments": ""}}]}))
            for piece in _chunks(json.dumps(d.tool_args), 16):
                self._sse(chunk({"tool_calls": [{"index": 0, "function": {"arguments": piece}}]}))
                time.sleep(STREAM_DELAY)
            self._sse(chunk({}, "tool_calls"))
        else:
            self._sse(chunk({"role": "assistant", "content": ""}))
            pieces = list(_chunks(d.text))
            for i, piece in enumerate(pieces):
                if STATE[provider] == "flaky" and i == len(pieces) // 2:
                    self._sse(json.dumps({"error": {"message": "The server had an error while processing your request. (mock)", "type": "server_error"}}))
                    return
                self._sse(chunk({"content": piece}))
                time.sleep(STREAM_DELAY)
            self._sse(chunk({}, "stop"))
        if (body.get("stream_options") or {}).get("include_usage"):
            self._sse(json.dumps({"id": cid, "object": "chat.completion.chunk", "created": created, "model": model, "choices": [],
                                  "usage": {"prompt_tokens": in_tok, "completion_tokens": out_tok, "total_tokens": in_tok + out_tok}}))
        self._sse("[DONE]")


def main():
    port = int(os.environ.get("MOCK_PORT", "8787"))
    srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    srv.daemon_threads = True
    print(f"✈  AsyncAir control tower on http://localhost:{port}  (dashboard at /)", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
