"""Starts a private control tower on a free port for each test session."""
import json
import os
import threading
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from mock.server import STATE, Handler


@pytest.fixture(scope="session")
def tower():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}"
    os.environ["MOCK_URL"] = url
    os.environ["ASYNCAIR_MODE"] = "mock"
    yield url
    srv.shutdown()


@pytest.fixture(autouse=True)
def all_clear():
    for p in STATE:
        STATE[p] = "ok"
    yield
    for p in STATE:
        STATE[p] = "ok"


def set_chaos(url: str, provider: str, mode: str) -> None:
    req = urllib.request.Request(f"{url}/_chaos", data=json.dumps({"provider": provider, "mode": mode}).encode(), method="POST")
    urllib.request.urlopen(req).read()
