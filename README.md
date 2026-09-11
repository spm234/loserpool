# Loser Pool

A tool for a "loser pool" (a survivor pool played in reverse): each week
every entry picks one NFL team they believe will **lose**. A win by your
picked team costs a life; the pool's rule this season gives everyone 2
lives (a $30 buy-in prepays the buy-back). No picking the same team twice
until a playoff reset. If it reaches the playoffs with entries still alive,
everyone's used-team list clears and the field picks from the playoff
teams; multiple survivors after the Super Bowl split the pot.

This repo runs itself: a scheduled GitHub Action pulls the pool operator's
public Google Sheet (everyone's actual picks) and The Odds API (schedule,
spreads, results), updates the database, and republishes a static
dashboard — no server, no one has to run anything by hand. See
**[the live dashboard](https://spm234.github.io/loserpool/)** once Pages is
turned on (one-time setup below).

## How the automation works

`.github/workflows/refresh.yml` runs a few times a day on Thursday, Sunday
and Monday (the pool's actual game days — tune the cron if you want a
different cadence) and on manual trigger (Actions tab → Refresh Loser Pool
dashboard → Run workflow):

1. Figures out the current NFL week from today's date (`current-week`).
2. Pulls whatever's currently on The Odds API's board, matches each game to
   a week by kickoff date, records spreads, and fetches final scores for
   games that have finished (`sync-week`) — then settles any picks those
   results resolve (lives lost, eliminations).
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

## One-time setup

1. **Enable GitHub Pages**: Settings → Pages → Source: **Deploy from a
   branch** → Branch: `main` → folder: **/docs** → Save. GitHub gives you a
   URL like `https://spm234.github.io/loserpool/` within a minute or two.
   (This repo is public, so the Pages site is too — see "Privacy" below.)
2. **Add the Odds API key**: sign up free at
   [the-odds-api.com](https://the-odds-api.com), then Settings → Secrets and
   variables → Actions → **New repository secret** → name
   `THE_ODDS_API_KEY`, paste your key. Without this, the workflow still
   runs (sheet picks + dashboard keep working) but skips schedule/spread/
   result syncing and logs a warning.
3. **Check the season config** (repo Variables, same Settings page, tab
   "Variables" — all optional, the workflow has working defaults baked in):
   - `SEASON_YEAR` (default `2026`)
   - `SEASON_WEEK1_DATE` (default `2026-09-08`) — the Tuesday before the
     season opener; used to compute "what week is it" automatically. Only
     matters for the regular season — playoff weeks aren't auto-computed
     (see `season_calendar.py`'s docstring for why), so once the playoffs
     start you'll want to run `sync-week --week 19` (etc.) manually or
     adjust the workflow.
   - `POOL_SHEET_ID` (defaults to the actual "Loser Pool 26-27" sheet's ID)
     — change this if the operator starts a new sheet next season.
4. **Mark your own entry** so the dashboard shows recommendations for it —
   the sheet sync creates every entry it sees, but doesn't know which one
   is "yours":
   ```
   python -m loser_pool.cli mark-mine --name "Sean M"
   ```
   Run this once locally against the committed `loser_pool.db`, commit it,
   and push — the next scheduled run keeps the flag (get_or_create_entry
   never resets `is_mine` on a row that already exists).
5. Trigger the workflow once manually (Actions tab) to build the first
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

# Bring in this week's games/spreads/results from The Odds API:
THE_ODDS_API_KEY=... python -m loser_pool.cli sync-week --season 2026 --week 1

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

- **Win probability**: a market spread (from The Odds API, when the game
  is close enough to be on its board) converts to a win probability via
  the normal-CDF margin model (NFL margins ≈ Normal(spread, 13.86)).
  Further out than that, an **Elo rating model** projects it instead
  (FiveThirtyEight-style: home-field-advantage constant, margin-of-victory
  weighted updates after every result). All 32 teams start flat at the
  same rating — there's no built-in preseason power-rating source (see
  "Why Elo, not a real power-rating service" below) — so early-season Elo
  projections are weak until a few weeks of real results feed in; lean on
  actual market spreads (`sync-week` records these automatically once
  they're posted) rather than early Elo numbers when picking.
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
  (`team_outlook.known_weeks`) — see "Why Elo..." below for extending
  that beyond what `sync-week` has discovered on its own.
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
  three are capped to whatever weeks `sync-week` has actually discovered
  so far — there's no full 18-week schedule preloaded (see below), so
  early in the season these will only cover 1-2 weeks and fill in as the
  season goes.
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
The Odds API (used here for real market spreads/results) doesn't publish
season-long power ratings this far ahead of each game, so Elo — built from
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
use each team") work across all 18 weeks immediately instead of filling
in week by week as `sync-week` discovers each one. This tool still can't
fetch such a page itself (see above), but it can import one you paste in:
```
python -m loser_pool.cli import-season-spreads --season 2026 --file season_spreads.txt
```
See `loser_pool/season_spreads.py`'s docstring for the exact text shape
it expects. **A real market spread always wins**: this import only ever
fills in a game that doesn't have a real spread from `sync-week` yet, and
refreshing with an updated grid only touches games still on their earlier
projection — it can't clobber real market data even if a stale projection
is pasted back in later. Worth re-pasting occasionally as the season's
projections move, or once real lines replace them week to week (which
happens automatically).

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
