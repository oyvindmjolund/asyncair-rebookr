# Instructor guide · AsyncAir masterclass

Graduates only ever talk to the mock control tower. Real keys are used on **your** Codespace for
the Saturday data run and for the live switch on slide 46.

## 1 · Repo (once)

1. Create a **public** repo on your **personal** GitHub account (e.g. `asyncair-rebookr`).
   Organisation repos often block public ports, and graduates on personal accounts can't open
   Codespaces on a private repo.
2. Push this folder **with git**, not by uploading in the browser (browser upload drops the
   executable bit on scripts):
   ```bash
   git init && git add . && git commit -m "AsyncAir starter" && git branch -M main
   git remote add origin https://github.com/<you>/asyncair-rebookr.git && git push -u origin main
   ```
   Credential trouble on your machine? Upload in the browser instead, then follow **1b** below.
3. Settings → General → tick **Template repository**.
4. Open a Codespace and check: `curl localhost:8787/health` and `pytest -q` → **10 passed, 5 failed**.
   The 5 failures are the exercise.

## 1b · Uploaded via the browser? Fix it from a Codespace

A browser upload has two side effects: scripts lose their executable flag, and files or folders
starting with a dot can go missing. A Codespace is already signed in to your repo, so git works
there without any credential setup.

1. **Check the file list on GitHub.** These must be there: `.devcontainer/devcontainer.json`,
   `.gitignore`, `.env.example`. This must **not** be there: `.env`. If `.env` was uploaded, delete
   it and rotate all keys at once - the repo is public and the file stays in the history.
   A missing file can be added with *Add file → Create new file*, typing the full path as the name.
2. **Open a Codespace:** repo page → *Code → Codespaces → Create codespace on main*.
3. **Restore the executable flag** in the Codespace terminal:
   ```bash
   git update-index --chmod=+x scripts/reveal_solutions.sh
   git commit -m "Make reveal_solutions.sh executable"
   git push
   ```
4. **Verify:**
   ```bash
   git ls-files -s scripts/reveal_solutions.sh
   ```
   The line should start with `100755` (it was `100644`).
5. **Smoke test** in the same Codespace: `curl localhost:8787/health` → `{"ok": true}`, and
   `pytest -q` → **10 passed, 5 failed**.

Everything in the course uses `bash scripts/reveal_solutions.sh`, which works with or without the
flag. Step 3 just makes `./scripts/reveal_solutions.sh` work too.

Keep using this Codespace for later changes to the repo: edit, `git commit`, `git push`.

## 2 · Keys (once)

Either a `.env` in the repo root (`cp .env.example .env`, fill in, `set -a; source .env; set +a` in
every new terminal) or the same names as **Codespaces secrets** on your GitHub account
(Settings → Codespaces → Secrets, give them access to the repo) - then they're just there.

Your setup, Azure via the Foundry AI Gateway:

```bash
ANTHROPIC_API_KEY=<anthropic key>
OPENAI_API_KEY=<openai key>
AZURE_OPENAI_API_KEY=<gateway subscription key>
AZURE_OPENAI_ENDPOINT=https://aigw-ccaclaudefoundry.azure-api.net/foundry-ccaclaudefoundry-swe
AZURE_OPENAI_API_VERSION=2024-10-21
AZURE_OPENAI_KEY_HEADER=x-api-key
```

`config.toml` → `[providers.azure]` holds your Foundry **deployment** names (`gpt-5-mini`, `gpt-5`).
`.env` is in `.gitignore`. Keep it there.

## 3 · Saturday (about 1 hour)

```bash
bash scripts/reveal_solutions.sh                  # YOUR copy only - never push this
ASYNCAIR_MODE=live python scripts/check_live.py   # all ✓ (azure fast may skip a tool call now and then - fine)
```

Optional but recommended: put current list prices under `[prices.*]` in `config.toml` and set
`verified = true`. Otherwise the cost column on slide 44 is shown as «–».

Then one command produces everything for slides 36-39, 43 and 44:

```bash
ASYNCAIR_MODE=live python -m evals.deck_data                 # ~5-10 min
ASYNCAIR_MODE=live python -m evals.deck_data --judge-check   # + slide 42, takes longer
```

**Send `evals/deck/deck-data.md` to Claude** - the numbers and answers get built into the deck.
Full reports stay in `evals/results/` as backup.

Then rehearse the whole thing once, including pressing the red button for real.
Rehearse from the dashboard with all three windows (dashboard, deck, script), so do the
script step under Sunday already now.

**Before you ever push again:** `git checkout rebookr/llm/openai_provider.py` (removes the solution).

## 4 · Sunday

**Before you start (each Codespace, once):**
- [ ] **Put the speaker script in place:** drag your `manus.md` into `private/` in the VS Code
      Explorer, so it ends up as `private/manus.md`. It is git-ignored and never pushed, so a new
      Codespace does **not** have it. Check: `ls private/manus.md`, then *Åpne manus* on the
      dashboard shows the script, not «Fant ikke manuset». (Fallback: pick the file in the script window.)
- [ ] Port 8787 **Public**, port 8788 **Private** (add 8788 in the Ports tab if it's missing).
- [ ] Open the dashboard (8788), allow pop-ups, open the deck and the script.

**Shared control tower.** Codespace → Ports tab → right-click 8787 → *Port Visibility → Public*.
`python -m rebookr join` points graduates at `[mock] shared_url` in `config.toml`. If your
Codespace URL has changed, update `shared_url` and push before the session.
The deck fills in the tower URL on slide 30 when you open it from the dashboard; check that it ends
in `-8787.app.github.dev`. Test `https://<address>/health` in an incognito window.
A Codespace stops after 30 idle minutes: open it early and keep a terminal busy.

**Two ports.** 8787 (Public) serves the APIs, `/vote` and `/results`. The dashboard and every
control route (`POST /_chaos`, `/_vote/control`, `/_reset_scores`) live on **8788**, which you
leave **Private**: Codespaces then only lets your own GitHub login in. On 8787 those routes answer
403, so graduates can't press the red button or reset the scoreboard. Open the dashboard from the
Ports tab (8788) in a browser where you're signed in to GitHub. The dashboard shows the public
tower URL for slide 30. In an older Codespace, forward 8788 by hand in the Ports tab.

**The deck runs from the tower.** On the dashboard (8788), *Åpne presentasjonen* opens `/deck` in
its own window: drag it to the projector and press `F` there. The dashboard then shows the timer
(elapsed, slide, section, red when late) with *Tilbakestill* and *Pause*, so nothing timing-related
is on the projector. The tower fills in the tower URL (slide 30, and the QR code on 35) and the
repo link (slide 50) from the Codespace. The file is `deck/asyncair-masterclass.html`, read on
every request, so an updated deck needs no restart. Allow pop-ups for the 8788 address. The deck
keeps running if the Codespace stops, but the voting and the red button don't. Backup: the same
file on claude.ai, with the clock icon's timer window as before.

**Speaker script on a second screen.** *Åpne manus* on the dashboard opens `/manus`: the script
split per slide, with the current slide highlighted and scrolled to the top, the next slide, the
timer, and how many clicks the slide has left. It follows the deck, and arrow keys, Page Up/Down or a
clicker in that window move the deck. The script is read from `private/manus.md`, which is
git-ignored so graduates never see it: drag the file into `private/` in the Codespace (VS Code
Explorer), or pick it in the script window, which then remembers it in that browser.
Suggested screens: laptop = dashboard + terminal, extra screen = script, projector = deck.

**Blind test voting (slides 35-39)** runs in the same tower, no Mentimeter needed:
- Phones: `<tower-URL>/vote` (slide 35 shows a QR code once the URL is on slide 30).
- You: the *Blindtest · avstemning* panel on the dashboard - open round 1, 2, 3, then *Steng*.
- Projector after round 3: `<tower-URL>/results`.
- Rehearse it Saturday from your own phone, then *Nullstill alle stemmer*.

Dashboard keys: `Space` red button · `0` all clear · `1/2/3` toggle a provider · `S` slow ·
`R` rate limit · `F` dies mid-stream.

| Slide | What you run |
|---|---|
| 7 | `python -m legacy.storm`, then Space on the dashboard → stack trace. Press `0` afterwards |
| 10 | open `legacy/` |
| 17 | (on the slide) |
| 24 | graduates: `python -m rebookr join "team"`, `code rebookr/llm/openai_provider.py`, `pytest tests/test_openai_provider.py -v`; stragglers: `bash scripts/reveal_solutions.sh` (keeps their version as `.mine`) |
| 28 | `cd ts && npm run demo -- --stream "Will I get compensation?"` (optional) |
| 30 | *Reset scores*; graduates: `python -m rebookr storm` (join first if they didn't on 24); click the scoreboard onto the slide; you: Space, `2`, `0` |
| 32 | `F` on the dashboard, then `python -m rebookr ask "Will I get compensation?" --stream`; `0` afterwards |
| 46 | `ASYNCAIR_MODE=live python -m rebookr ask "My flight KRS to OSL was cancelled"`, swap the first two entries of `routes.rebooking.chain`, run again |

### If something breaks
- **Tower URL unreachable:** everyone runs `python -m rebookr join "team" --local`, then `python -m mock.chaos anthropic down` on your signal.
- **Azure fails live:** remove the `AZURE_` lines from `.env`, reload. Graduates still see Azure via the tower.
- **Live APIs fail on slide 46:** do the switch in mock mode. Same point.
- **Voting page doesn't load on phones:** fingers - one, two or three for A, B, C.
