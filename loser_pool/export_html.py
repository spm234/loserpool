"""Renders a static HTML dashboard — no server, no live DB access. This is
a snapshot: the GitHub Actions workflow regenerates and commits it on
every scheduled sync, which is what makes it "live" without anyone running
a command by hand.

Names are shown (not anonymized) — same visibility the pool's own Google
Sheet already has ("anyone with the link" can view it), so this isn't a
bigger exposure than what already exists.

Layout is modeled on clevanalytics' Survivor Optimizer UI: a stat-tile
strip, "recommended pick + backups" cards for the current week, and a
reference full-season path table below. Team logos hotlink to ESPN's
public logo CDN (teams.py); an unrecognized team name just renders without
one (onerror hides a broken image rather than showing a broken-image icon).
"""
from __future__ import annotations

import html
import sqlite3
from datetime import datetime, timezone
from typing import Dict, List, Optional

from .config import LoserPoolConfig
from .optimizer import WeeklyRecommendation, full_season_plan, recommend_week
from .picks import used_teams
from .sheets_sync import PickOwnership
from .team_outlook import (
    best_week_per_team,
    known_weeks,
    season_to_date_team_usage,
    weekly_biggest_underdogs,
)
from .teams import logo_url

STYLE = """
:root {
  color-scheme: light dark;
  --bg: #f4f5f7; --card: #ffffff; --border: #e4e6eb; --text: #14161a;
  --muted: #6b7280; --accent: #d9662a; --accent-bg: #fdf1e9; --accent-border: #f0b487;
  --navy: #0f1f3d; --good: #1f8a4c; --warn: #b8860b; --bad: #c0392b;
  --tile-bg: #f8f9fb;
  --pill-chalk-bg: #fdeee2; --pill-chalk-text: #b5551a;
  --pill-leverage-bg: #e9f7ee; --pill-leverage-text: #1f8a4c;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #101216; --card: #1a1d24; --border: #2a2d35; --text: #e8e8ea;
    --muted: #9aa0ab; --accent: #f0924f; --accent-bg: #2a2116; --accent-border: #7a4a20;
    --navy: #dbe6ff; --tile-bg: #181b21;
    --pill-chalk-bg: #2a2116; --pill-chalk-text: #e2a06a;
    --pill-leverage-bg: #16281d; --pill-leverage-text: #6fcf97;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; padding: 24px 16px 48px; background: var(--bg); color: var(--text);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
}
.wrap { max-width: 1000px; margin: 0 auto; }
.header-row { display: flex; align-items: baseline; justify-content: space-between; flex-wrap: wrap; gap: 8px; }
h1 { font-size: 1.5rem; margin: 0 0 4px 0; color: var(--navy); }
.subtitle { color: var(--muted); margin-bottom: 1.25em; font-size: 0.88rem; }
.badge {
  display: inline-block; padding: 4px 12px; border-radius: 999px; font-size: 0.8rem;
  font-weight: 600; background: var(--accent-bg); color: var(--accent); border: 1px solid var(--accent-border);
}
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; margin-bottom: 24px; }
.tile { background: var(--tile-bg); border: 1px solid var(--border); border-radius: 10px; padding: 14px 16px; }
.tile .value { font-size: 1.5rem; font-weight: 700; color: var(--navy); }
.tile .label { font-size: 0.8rem; color: var(--muted); margin-top: 2px; }
.card {
  background: var(--card); border: 1px solid var(--border); border-radius: 10px;
  padding: 16px 20px; margin-bottom: 24px; overflow-x: auto;
}
h2 { font-size: 1.05rem; margin: 0 0 12px 0; color: var(--navy); }
h2 .hint { font-weight: 400; color: var(--muted); font-size: 0.78rem; text-transform: none; letter-spacing: 0; }
h3 { font-size: 0.95rem; margin: 18px 0 8px 0; }
table { border-collapse: collapse; width: 100%; font-size: 0.88rem; }
th, td { text-align: left; padding: 7px 10px; border-bottom: 1px solid var(--border); white-space: nowrap; }
th { color: var(--muted); font-weight: 600; font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.03em; }
tr:last-child td { border-bottom: none; }
.eliminated { opacity: 0.5; text-decoration: line-through; }
.lives-2 { color: var(--good); font-weight: 600; }
.lives-1 { color: var(--warn); font-weight: 600; }
.lives-0 { color: var(--bad); font-weight: 600; }
.team { display: inline-flex; align-items: center; gap: 6px; white-space: nowrap; }
.team img { width: 20px; height: 20px; object-fit: contain; }
.pick-cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 14px; margin-bottom: 8px; }
.pick-card { border: 1px solid var(--border); border-radius: 10px; padding: 14px 16px; }
.pick-card.recommended { border-color: var(--accent-border); background: var(--accent-bg); }
.pick-card .kicker { font-size: 0.72rem; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; margin-bottom: 6px; }
.pick-card.recommended .kicker { color: var(--accent); }
.pick-card:not(.recommended) .kicker { color: var(--muted); }
.pick-card .matchup { display: flex; align-items: center; gap: 8px; font-size: 1.05rem; font-weight: 700; margin-bottom: 8px; }
.pick-card .matchup img { width: 26px; height: 26px; object-fit: contain; }
.pick-card .stat-row { display: flex; justify-content: space-between; font-size: 0.85rem; color: var(--muted); padding: 2px 0; }
.pick-card .stat-row b { color: var(--text); }
.pill { display: inline-block; padding: 2px 9px; border-radius: 999px; font-size: 0.72rem; font-weight: 600; margin-top: 8px; }
.pill.chalk { background: var(--pill-chalk-bg); color: var(--pill-chalk-text); }
.pill.leverage { background: var(--pill-leverage-bg); color: var(--pill-leverage-text); }
.trajectory { color: var(--muted); font-size: 0.82rem; white-space: normal; }
"""


def _esc(value) -> str:
    return html.escape(str(value)) if value is not None else ""


def _lives_class(lives: int) -> str:
    return f"lives-{max(0, min(2, lives))}"


def _team_html(name: str) -> str:
    url = logo_url(name)
    img = f"<img src='{_esc(url)}' onerror=\"this.remove()\">" if url else ""
    return f"<span class='team'>{img}{_esc(name)}</span>"


def _note_badge(is_top_pick: bool, ownership_frac: float, p_lose: float) -> str:
    if is_top_pick and ownership_frac >= 0.30:
        return "<span class='pill chalk'>Heavy chalk</span>"
    if ownership_frac <= 0.10 and p_lose >= 0.65:
        return "<span class='pill leverage'>Good leverage</span>"
    return ""


def _pick_card(rank: int, rec: WeeklyRecommendation, ownership_by_team: Dict[str, PickOwnership]) -> str:
    kicker = "Recommended" if rank == 0 else f"Backup option {rank}"
    loc = "home" if rec.is_home else "away"
    own = ownership_by_team.get(rec.team)
    public_pct = f"{own.fraction_of_submitted:.1%}" if own else "—"
    badge = _note_badge(rank == 0, own.fraction_of_submitted if own else 0.0, rec.p_lose)
    survive_row = ""
    if rec.p_survive_season_if_picked is not None:
        survive_row = (
            f"<div class='stat-row'><span>Season survival</span>"
            f"<b>{rec.p_survive_season_if_picked:.1%}</b></div>"
        )
    return f"""
<div class="pick-card {'recommended' if rank == 0 else ''}">
  <div class="kicker">{kicker}</div>
  <div class="matchup">{_team_html(rec.team)} <span style="color:var(--muted);font-weight:400;font-size:0.8rem">{loc} vs</span> {_team_html(rec.opponent)}</div>
  <div class="stat-row"><span>Loses</span><b>{rec.p_lose:.1%}</b></div>
  <div class="stat-row"><span>Public pick %</span><b>{public_pct}</b></div>
  {survive_row}
  {badge}
</div>"""


def _render_recommendations(
    conn: sqlite3.Connection,
    season_year: int,
    week_number: int,
    entries,
    ownership_by_team: Dict[str, PickOwnership],
    cfg: LoserPoolConfig,
) -> str:
    my_entries = [e for e in entries if e["is_mine"] and not e["eliminated"]]
    if not my_entries:
        return ""

    sections = []
    for e in my_entries:
        recs = recommend_week(conn, season_year, week_number, e["id"])
        section = f"<h3>{_esc(e['display_name'])} — {e['lives_remaining']} live(s)</h3>"
        if not recs:
            section += "<p style='color:var(--muted)'>No available teams with a game this week.</p>"
            sections.append(section)
            continue

        cards = "".join(_pick_card(i, r, ownership_by_team) for i, r in enumerate(recs[:3]))
        section += f"<div class='pick-cards'>{cards}</div>"

        if len(recs) > 3:
            more_rows = "".join(
                f"<tr><td>{_team_html(r.team)}</td><td>{'home' if r.is_home else 'away'} vs {_team_html(r.opponent)}</td>"
                f"<td>{r.p_lose:.1%}</td></tr>"
                for r in recs[3:8]
            )
            section += f"<table><tr><th>Team</th><th>Matchup</th><th>Loses</th></tr>{more_rows}</table>"

        remaining_weeks = list(range(week_number, min(week_number + 8, 19)))
        exclude = used_teams(conn, e["id"], season_year)
        plan = full_season_plan(conn, season_year, remaining_weeks, exclude_teams=exclude, cfg=cfg)
        if len(plan) > 1:
            plan_rows = "".join(
                f"<tr><td>Week {p.week_number}</td><td>{_team_html(p.team)}</td>"
                f"<td>{'home' if p.is_home else 'away'} vs {_team_html(p.opponent)}</td>"
                f"<td>{p.p_lose:.1%}</td></tr>"
                for p in plan
            )
            section += (
                "<h3 style='margin-top:20px'>Reference full-season path "
                "<span style='font-weight:400;color:var(--muted);font-size:0.8rem'>"
                "(unlimited-life optimal — ignores your 2-life limit, see README)</span></h3>"
                f"<table><tr><th>Week</th><th>Pick</th><th>Opponent</th><th>Loses</th></tr>{plan_rows}</table>"
            )
        sections.append(section)

    return f"<div class='card'><h2>This week's recommendations</h2>{''.join(sections)}</div>"


def _render_team_usage(conn: sqlite3.Connection, season_year: int) -> str:
    usage = season_to_date_team_usage(conn, season_year)
    rows = "".join(
        f"<tr><td>{_team_html(u.team)}</td><td>{u.times_picked}</td></tr>" for u in usage
    )
    return f"""
<div class="card">
  <h2>Team usage so far <span class="hint">— how many entries have already used each team this cycle (each can only go once)</span></h2>
  <table><tr><th>Team</th><th>Times picked</th></tr>{rows}</table>
</div>"""


def _render_weekly_underdogs(conn: sqlite3.Connection, season_year: int, cfg: LoserPoolConfig) -> str:
    weeks = known_weeks(conn, season_year)
    if not weeks:
        return ""
    top_by_week = weekly_biggest_underdogs(conn, season_year, weeks, cfg=cfg, top_n=3)
    rows = []
    for week in weeks:
        options = top_by_week.get(week, [])
        cells = "".join(
            f"<td>{_team_html(o.team)} <span class='trajectory'>{o.p_lose:.0%}</span></td>" for o in options
        )
        cells += "<td>—</td>" * (3 - len(options))
        rows.append(f"<tr><td>Week {week}</td>{cells}</tr>")
    return f"""
<div class="card">
  <h2>Week-over-week biggest underdogs <span class="hint">— highest projected loss probability each week, league-wide</span></h2>
  <table><tr><th>Week</th><th>Biggest underdog</th><th>2nd</th><th>3rd</th></tr>{''.join(rows)}</table>
</div>"""


def _render_team_outlook(conn: sqlite3.Connection, season_year: int, cfg: LoserPoolConfig) -> str:
    from .team_outlook import team_week_matrix

    weeks = known_weeks(conn, season_year)
    if not weeks:
        return ""
    matrix = team_week_matrix(conn, season_year, weeks, cfg=cfg)
    best = best_week_per_team(matrix)
    rows = []
    for opt in best:
        loc = "home" if opt.is_home else "away"
        trajectory = " · ".join(
            f"wk{w}: {matrix[opt.team][w].p_lose:.0%}" for w in sorted(matrix[opt.team])
        )
        rows.append(
            f"<tr><td>{_team_html(opt.team)}</td>"
            f"<td>Week {opt.week_number} ({loc} vs {_esc(opt.opponent)}) — <b>{opt.p_lose:.0%}</b></td>"
            f"<td class='trajectory'>{trajectory}</td></tr>"
        )
    return f"""
<div class="card">
  <h2>Best week to use each team <span class="hint">— when they project as the biggest underdog, among weeks with a known schedule</span></h2>
  <table><tr><th>Team</th><th>Best week</th><th>All known weeks</th></tr>{''.join(rows)}</table>
</div>"""


def render_dashboard_html(
    conn: sqlite3.Connection,
    season_year: int,
    week_number: int,
    *,
    cfg: Optional[LoserPoolConfig] = None,
    ownership: Optional[List[PickOwnership]] = None,
    generated_at: Optional[datetime] = None,
) -> str:
    cfg = cfg or LoserPoolConfig.load(conn)
    generated_at = generated_at or datetime.now(timezone.utc)
    ownership_by_team = {o.team: o for o in (ownership or [])}

    entries = conn.execute(
        "SELECT * FROM lp_entry ORDER BY eliminated ASC, lives_remaining DESC, display_name ASC"
    ).fetchall()
    alive = [e for e in entries if not e["eliminated"]]
    eliminated = [e for e in entries if e["eliminated"]]

    leader = ownership[0] if ownership else None
    tiles = [
        (str(len(alive)), "Entries alive"),
        (str(len(eliminated)), "Eliminated"),
        (str(len(entries)), "Total entries"),
        (f"{leader.team} ({leader.fraction_of_submitted:.0%})" if leader else "—", "Most-picked team"),
    ]
    tiles_html = "".join(
        f"<div class='tile'><div class='value'>{_esc(v)}</div><div class='label'>{_esc(l)}</div></div>"
        for v, l in tiles
    )

    standings_rows = []
    for e in entries:
        used = sorted(used_teams(conn, e["id"], season_year))
        status = f"OUT (wk {e['eliminated_week']})" if e["eliminated"] else f"{e['lives_remaining']} live(s)"
        row_class = "eliminated" if e["eliminated"] else _lives_class(e["lives_remaining"])
        used_html = " ".join(_team_html(t) for t in used) or "—"
        standings_rows.append(
            f"<tr class='{row_class}'><td>{_esc(e['display_name'])}</td><td>{_esc(status)}</td>"
            f"<td>{used_html}</td></tr>"
        )

    ownership_html = ""
    if ownership:
        rows = "".join(
            f"<tr><td>{_team_html(o.team)}</td><td>{o.count}</td>"
            f"<td>{o.fraction_of_submitted:.1%}</td><td>{o.fraction_of_all_entries:.1%}</td></tr>"
            for o in ownership
        )
        ownership_html = f"""
<div class="card">
  <h2>Week {week_number} field ownership</h2>
  <table>
    <tr><th>Team picked</th><th>Count</th><th>% of submitted</th><th>% of full field</th></tr>
    {rows}
  </table>
</div>"""

    recommendations_html = _render_recommendations(conn, season_year, week_number, entries, ownership_by_team, cfg)
    team_usage_html = _render_team_usage(conn, season_year)
    weekly_underdogs_html = _render_weekly_underdogs(conn, season_year, cfg)
    team_outlook_html = _render_team_outlook(conn, season_year, cfg)

    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Loser Pool {season_year} — Week {week_number}</title>
<style>{STYLE}</style>
</head>
<body>
<div class="wrap">
<div class="header-row">
  <div>
    <h1>Loser Pool {season_year}</h1>
    <div class="subtitle">Week {week_number} · last updated {generated_at.strftime('%Y-%m-%d %H:%M UTC')}</div>
  </div>
  <span class="badge">Week {week_number}</span>
</div>

<div class="tiles">{tiles_html}</div>

{recommendations_html}

<div class="card">
  <h2>Standings</h2>
  <table>
    <tr><th>Entry</th><th>Status</th><th>Used teams</th></tr>
    {''.join(standings_rows)}
  </table>
</div>

{ownership_html}
{team_usage_html}
{weekly_underdogs_html}
{team_outlook_html}
</div>
</body>
</html>
"""
