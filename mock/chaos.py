"""Flip the red button from a terminal.

  python -m mock.chaos anthropic down      # down | slow | ratelimit | ok
  python -m mock.chaos all ok
  python -m mock.chaos                     # show status
"""
import json
import os
import sys
import urllib.request

url = os.environ.get("MOCK_URL", "http://localhost:8787").rstrip("/")
if len(sys.argv) == 3:
    body = json.dumps({"provider": sys.argv[1], "mode": sys.argv[2]}).encode()
    req = urllib.request.Request(f"{url}/_chaos", data=body, method="POST", headers={"Content-Type": "application/json"})
    print(json.loads(urllib.request.urlopen(req).read())["state"])
else:
    print(json.loads(urllib.request.urlopen(f"{url}/_chaos").read())["state"])
