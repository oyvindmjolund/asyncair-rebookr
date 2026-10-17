# ✈ AsyncAir · Rebookr

*Your flight will resolve eventually.*

You're the Capgemini team on the AsyncAir account. Three weeks ago the CTO asked you to make
**Rebookr**, the airline's AI rebooking assistant, "enterprise-ready". It's Friday, 16:47.
A storm has grounded every flight, 40,000 passengers need rebooking, and the phone is ringing.

## 1. Get going (5 minutes)

1. Click **Code → Codespaces → Create codespace on main**. Wait for the setup to finish.
2. Open a terminal and check that the control tower (our mock LLM server) is running:
   ```bash
   curl localhost:8787/health
   ```
   If that fails, start it in its own terminal: `python -m mock.server`
3. Join: set your team name (it shows up on the scoreboard) and point Rebookr at the
   instructor's control tower. Saved in `.asyncair.toml`, so it survives new terminals:
   ```bash
   python -m rebookr join "your-team-name"
   ```
   Tower not reachable? `python -m rebookr join "your-team-name" --local` uses the one in your Codespace.
4. Talk to Rebookr:
   ```bash
   python -m rebookr ask "My flight KRS to OSL tonight was cancelled. Can you rebook me?"
   python -m rebookr ask "What does this say?" --image assets/boarding_pass.png
   python -m rebookr ask "Will I get compensation?" --stream
   ```

You don't need any API keys. The control tower speaks the same wire format as Anthropic, OpenAI
and Azure, so the **real vendor SDKs** talk to it, but nothing leaves the room and nothing costs money.

## 2. Map of the repo

| Path | What it is |
|---|---|
| `legacy/` | Rebookr v1. Vendor SDK in every file. Exhibit A. |
| `rebookr/llm/types.py` | The provider-neutral contract. No vendor in sight. |
| `rebookr/llm/anthropic_provider.py` | Anthropic adapter (finished, read it) |
| `rebookr/llm/openai_provider.py` | OpenAI adapter (**your exercise**) |
| `rebookr/llm/azure_provider.py` | Azure adapter. Look how short it is. Why? |
| `rebookr/llm/router.py` | Model router: routes, fallback chain, circuit breaker |
| `rebookr/agent.py` | The agent loop. Notice: zero vendor imports. |
| `config.toml` | Routes, model aliases, resilience settings. Switching provider = editing this. |
| `evals/` | Golden dataset + eval harness + blind taste test |
| `ts/` | The same abstraction in TypeScript, sharing the same `config.toml` |
| `mock/` | The control tower (mock server + red-button dashboard) |
| `deck/` | The slides from the masterclass (open the HTML file in a browser) |

## 3. Exercises

### Exercise 1 · Finish the OpenAI adapter
Anthropic is down and Rebookr has nowhere to fall back to. Open `rebookr/llm/openai_provider.py`
and complete **TODO 1, 2 and 3**. Run the tests until they're green:
```bash
pytest tests/test_openai_provider.py -v
```
Then check what happened to the Azure test. Why did it pass without you touching Azure?

### Exercise 2 · Survive the storm
Point at the instructor's control tower (URL on the slide) and start taking passengers:
```bash
export MOCK_URL="https://<on-the-slide>"
python -m rebookr storm
```
When the red button is pressed, does your Rebookr stay up? Things to try in `config.toml`:
reorder the `rebooking` chain, lower `breaker_failures`, set `retries_per_provider = 1`.
Watch the scoreboard.

Discuss: what happens if a provider dies **halfway through a streamed answer**?
(Hint: read `ModelRouter.stream`.)

### Exercise 3 · The blind taste test
Vote on your phone. Then we look at what the eval harness says:
```bash
python -m evals.run                      # all providers, Claude-tuned prompt
python -m evals.run --judge openai       # does the judge change the winner?
```

### Bonus
- Run the TypeScript version: `cd ts && npm run demo -- --stream "Will I get compensation?"`
- Add a `faq_cheap` route that only uses `fast` models, and use it for baggage questions.
- Add a test case to `evals/golden.jsonl` that you think one provider will fail.

**Stuck?** `bash scripts/reveal_solutions.sh` drops in the finished adapter. It overwrites
`rebookr/llm/openai_provider.py`, but saves your version as `openai_provider.py.mine` first.

## 4. Red-button controls

Open the **Ports** tab, then port **8788** to see the control tower dashboard (port 8787 serves the APIs only). Or from a terminal:
```bash
python -m mock.chaos anthropic down     # down | slow | ratelimit | ok
python -m mock.chaos all ok
```

## 5. Licensed to Switch

Green tests? Then you're licensed to switch. Download the badge and share it:

![Licensed to Switch](assets/licensed-to-switch.png)
