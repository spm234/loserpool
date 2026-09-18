# Loser Pool

A tool for a "loser pool" (a survivor pool played in reverse): each week
every entry picks one NFL team they believe will **lose**. A win by your
picked team costs a life; the pool's rule this season gives everyone 2
lives (a $30 buy-in prepays the buy-back). No picking the same team twice
until a playoff reset. If it reaches the playoffs with entries still alive,
everyone's used-team list clears and the field picks from the playoff
teams; multiple survivors after the Super Bowl split the pot.

This repo runs itself: a scheduled GitHub Action pulls the pool operator's
public Google Sheet (everyone's actual picks), settles any picks against
manually-recorded game results, updates the database, and republishes a
static dashboard — no server, no one has to run anything by hand beyond
entering each week's final scores (see "Recording results" below). See
**[the live dashboard](https://spm234.github.io/loserpool/)** once Pages is
turned on (one-time setup below).

## How the automation works

`.github/workflows/refresh.yml` runs hourly Thursday through Sunday (the
pool's actual game days) and every 6 hours the rest of the week — tune the
cron if you want a different cadence — and on manual trigger (Actions tab →
Refresh Loser Pool dashboard → Run workflow):

1. Figures out the current NFL week from today's date (`current-week`).
2. Settles every week so far (`settle-week`, week 1 through the current
   week) against whatever game results have been manually recorded so far
   — see "Recording results" below. A game with no recorded outcome yet
   just stays pending; settling is safe to re-run and only resolves picks
   whose game has since gotten a result.
3. Downloads the pool's Google Sheet as CSV via its public export URL — no
   Google auth needed, since the sheet is shared as "anyone with the link
   can view" — and bulk-applies every entry's picks (`import-sheet-picks`).
4. Renders the dashboard (`export-html`) and commits the refreshed database
   + `docs/index.html` back to the repo, which is what makes the change
   show up on the published page.

The database (`loser_pool.db`) is committed to the repo on purpose — a
GitHub Actions runner starts fresh every time, so state has to live
somewhere durable between runs, and a repo-committed SQLite file is the
simplest option for something this size. (Non-standard for most projects —
don't copy this pattern for anything with concurrent writers or real
secrets in the DB; there are none here.)

## Recording results

Game outcomes are entered by hand — there's no live-score API wired into
the automated workflow (there used to be one, backed by The Odds API, but
its free-tier key stopped being accepted, so this repo now runs entirely
off manually-recorded results instead of depending on that staying
available). Once you know a game's final score:
```
python -m loser_pool.cli record-result --season 2026 --week 1 \
  --away Bills --home Texans --outcome away --away-score 27 --home-score 23
```
`--outcome` is `home`, `away`, or `tie` (whichever side won); the score
flags are optional but feed the Elo model when both are given. Run this
locally against the committed `loser_pool.db`, commit it, and push — the
next scheduled run's `settle-week` pass picks it up and resolves any picks
riding on that game. `fetch-result` / `fetch-spread` / `sync-week` (all in
`loser_pool/live_data.py` / `sync.py`) still exist if you ever want to
point this at a working odds API key again, but nothing in the automated
workflow calls them.

## One-time setup

1. **Enable GitHub Pages**: Settings → Pages → Source: **Deploy from a
   branch** → Branch: `main` → folder: **/docs** → Save. GitHub gives you a
   URL like `https://spm234.github.io/loserpool/` within a minute or two.
   (This repo is public, so the Pages site is too — see "Privacy" below.)
2. **Check the season config** (repo Variables, Settings → Secrets and
   variables → Actions → tab "Variables" — all optional, the workflow has
   working defaults baked in):
   - `SEASON_YEAR` (default `2026`)
   - `SEASON_WEEK1_DATE` (default `2026-09-08`) — the Tuesday before the
     season opener; used to compute "what week is it" automatically. Only
     matters for the regular season — playoff weeks aren't auto-computed
     (see `season_calendar.py`'s docstring for why), so once the playoffs
     start you'll want to pass `--week 19` (etc.) explicitly to
     `record-result`/`settle-week`, or adjust the workflow's week range.
   - `POOL_SHEET_ID` (defaults to the actual "Loser Pool 26-27" sheet's ID)
     — change this if the operator starts a new sheet next season.
3. **Mark your own entry** so the dashboard shows recommendations for it —
   the sheet sync creates every entry it sees, but doesn't know which one
   is "yours":
   ```
   python -m loser_pool.cli mark-mine --name "Sean M"
   ```
   Run this once locally against the committed `loser_pool.db`, commit it,
   and push — the next scheduled run keeps the flag (get_or_create_entry
   never resets `is_mine` on a row that already exists).
4. Trigger the workflow once manually (Actions tab) to build the first
   dashboard rather than waiting for the next scheduled run.

## Privacy

The dashboard shows real participants' names, lives remaining, and picks —
this repo is public (GitHub Pages on a personal account requires that), and
so is the page. This isn't a bigger exposure than what already exists: the
pool's own Google Sheet is already shared as "anyone with the link can
view." If that ever changes, switch this repo to data-only (drop the Pages
step, keep the scheduled sync) or anonymize names in `export_html.py`.

## Running it yourself (without the automation)

```
pip install -r requirements.txt
python -m loser_pool.cli init-db
python -m loser_pool.cli config-set --season-week1-date 2026-09-08

# Record a finished game's result, then settle any picks it resolves:
python -m loser_pool.cli record-result --season 2026 --week 1 \
  --away Bills --home Texans --outcome away --away-score 27 --home-score 23
python -m loser_pool.cli settle-week --season 2026 --week 1

# Pull picks from the pool's sheet (download its CSV export yourself, or
# paste the same shape by hand — see loser_pool/sheets_sync.py for the
# exact grid format: name row, one column per week/playoff round):
python -m loser_pool.cli import-sheet-picks --season 2026 --file sheet.csv

python -m loser_pool.cli status --season 2026
python -m loser_pool.cli recommend --season 2026 --week 1 --entry "Sean M" --through-week 6
python -m loser_pool.cli export-html --season 2026 --week 1 --sheet-file sheet.csv --out docs/index.html
python -m loser_pool.cli export-team-pages --season 2026 --out-dir docs/teams
```

Run tests with `python -m pytest`.

## How picks get scored

- **Win probability**: a market spread converts to a win probability via
  the normal-CDF margin model (NFL margins ≈ Normal(spread, 13.86)). Real
  market spreads currently come in via the season-long moneyline grid
  (see "Why Elo, not a real power-rating service" below) rather than a
  live odds feed — automatic live-market fetching (`sync-week` /
  `fetch-spread`, backed by The Odds API) still exists as a manual command
  but isn't run by the automated workflow (see "Recording results"
  above). Where no spread exists at all yet, an **Elo rating model**
  projects it instead (FiveThirtyEight-style: home-field-advantage
  constant, margin-of-victory weighted updates after every result). All
  32 teams start flat at the same rating — there's no built-in preseason
  power-rating source — so early-season Elo projections are weak until a
  few weeks of real results feed in; lean on the moneyline-grid spreads
  rather than early Elo numbers when picking.
- **The optimizer** (`loser_pool/optimizer.py`) has two layers: `full-plan`
  is the theoretical best single sequence across a week range assuming
  unlimited lives (a linear-assignment solve via scipy — maximize the
  product of each picked team's weekly loss probability, one team per
  week, no repeats); `recommend` is the real weekly call, accounting for
  lives remaining and already-used teams, using Monte Carlo simulation
  (`loser_pool/simulation.py`) to re-rank by estimated season-survival
  probability rather than just this week's raw number — **this is what
  makes the top pick account for opportunity cost**: a team with a merely
  decent number now but a much bigger mismatch later can outrank a team
  that's the single highest number this week but goes nowhere better
  afterward, since burning the second team now costs nothing while
  burning the first one forfeits its better week. The dashboard's pick
  cards surface this directly with a "Peak week for this team" /
  "Bigger mismatch in Week N — consider saving" note per candidate, based
  on the same team-outlook data as the "best week to use each team" view.
  This only works as well as the schedule this tool actually knows about
  (`team_outlook.known_weeks`) — normally the full season, since the
  season-long moneyline grid import (see "Why Elo..." below) preloads
  every week up front.
- **Field ownership**: `sheet-ownership` / the dashboard's field-ownership
  table show current pick concentration per team, straight from the
  sheet — useful for the split-pot rule (a team fewer people share is
  worth more if it works out).
- **League-wide outlook views** (`loser_pool/team_outlook.py`, no entry or
  lives context — "what does the slate look like", not "what should I
  pick"): **team usage so far** (how many entries have already burned each
  team this cycle — every one of the 32 shows up, so it also reads as
  "what's still wide open"); **week-over-week biggest underdogs** (the
  top loss-probability team(s) each week, league-wide); **best week to use
  each team** (per team, which known week projects as its best mismatch,
  plus its trajectory across every other week already on the board). All
  three are capped to whatever weeks this tool actually knows the
  schedule for — normally all 18, via the season-long moneyline grid
  import (see below).
- **Per-team pages** (`export-team-pages`, `loser_pool/team_page.py`):
  every team name on the dashboard links to its own page — full known
  schedule with loss probability per game (green background = good pick
  target/heavy underdog, red = heavily favored and risky, matching the
  same thresholds as the rest of the tool), actual on-field record so
  far, current Elo rating, and every entry that's picked them this season
  with how it turned out. `docs/teams/index.html` (linked as "All Teams"
  from the dashboard header) lists all 32. Same known-weeks limitation as
  the outlook views above — a team's page only shows weeks this tool
  actually has a schedule for.

## Why Elo, not a real power-rating service

This tool was originally modeled on
[clevanalytics' Survivor Optimizer](https://clevanalytics.com/survivor-optimizer/)
and its [season-long spreads](https://clevanalytics.com/2026-nfl-season-long-spreads/)
page, but that site was unreachable from the sandbox this was built in
(blocked outright by the environment's network policy, not a login wall).
The Odds API (which this tool can optionally use for real market
spreads/results, via the manual `sync-week`/`fetch-spread` commands) doesn't
publish season-long power ratings this far ahead of each game, so Elo — built from
actual results as the season plays out — fills that gap without needing
a paid data source. If you have a better preseason power-rating or win-totals
source, seed it directly:
```
python -m loser_pool.cli import-win-totals --season 2026 --week 1 --file win_totals.csv  # "Team, WinTotal" per line
python -m loser_pool.cli import-elo-ratings --season 2026 --week 1 --file ratings.csv     # "Team, Rating" per line
```

**A better option once you have it**: a full-season "team x week" spread
grid (a team's own row, one cell per week showing their spread and
opponent — the shape most season-long-projection pages use) covers the
whole schedule in one shot, so the league-wide outlook views
(`team_outlook.py`'s "week-over-week biggest underdogs" and "best week to
use each team") work across all 18 weeks immediately rather than only
whatever weeks a live odds feed happens to have discovered so far. This
tool still can't fetch such a page itself (see above), but it can import
one you paste in:
```
python -m loser_pool.cli import-season-spreads --season 2026 --file season_spreads.txt
```
See `loser_pool/season_spreads.py`'s docstring for the exact text shape
it expects. **A real market spread always wins**: this import only ever
fills in a game that doesn't already have a real spread recorded (e.g.
via `record-spread`/`sync-week`), and refreshing with an updated grid only
touches games still on their earlier
projection — it can't clobber real market data even if a stale projection
is pasted back in later. Worth re-pasting occasionally as the season's
projections move.

**The best option, and what this repo now runs automatically**: a
season-long *moneyline* table (one row per team, one cell per week —
`loser_pool/season_moneylines.py`'s docstring has the exact shape) is more
accurate than a spread grid, because it gives BOTH teams' own line for the
same game — that's enough to **devig**: convert each side's American-odds
moneyline to its raw implied probability, then normalize the pair to sum
to 1, rather than reading one side's spread as an approximation. The
workflow fetches a fixed public sheet (`MONEYLINE_SHEET_ID`, a repo
Variable — defaults to the one already wired in) via its CSV export URL
every run, same no-auth pattern as the pool's pick sheet:
```
python -m loser_pool.cli import-season-moneylines --season 2026 --file moneylines.csv
```
Same non-clobbering rule as the spread-grid importer — a real market
spread always wins, and this one additionally supersedes a still-standing
spread-grid projection for the same game (moneylines are the more precise
source when both exist). If you're maintaining this sheet yourself,
editing it is enough — the next scheduled run (or a manual trigger) picks
up the change automatically, no re-paste through Claude needed.

## Open assumptions

- **Tie handling** (`tie_treated_as`, default `'bust'`): does a tied game
  count as a survived pick (push) or a bust? Rare enough (roughly once
  every couple of seasons) to leave as a documented guess until it
  actually comes up — flip it with `config-set --tie-treated-as survive`
  once confirmed with the pool operator.
- **Playoff week numbering**: mapped to week numbers 19-22 (Wild Card,
  Divisional, Conference, Super Bowl) so they sit on the same axis as the
  regular season internally — not auto-computed from a date, so pass
  `--week` explicitly once the playoffs start.
