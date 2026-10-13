import os

import anthropic

# "Temporary" - pointing at the control tower so the demo runs without keys.
BASE_URL = os.environ.get("MOCK_URL", "http://localhost:8787") + "/anthropic"
