"""Renders a static HTML dashboard — no server, no live DB access. This is
a snapshot: the GitHub Actions workflow regenerates and commits it on
every scheduled sync, which is what makes it "live" without anyone running
a command by hand.

Names are shown (not anonymized) — same visibility the pool's own Google
Sheet already has ("anyone with the link" can view it), so this isn't a
bigger exposure than what already exists.
"""
from __future__ import annotations

import html
import sqlite3
from datetime import datetime, timezone
from typing import List, Optional

from .config import LoserPoolConfig
from .optimizer import recommend_week
from .picks import used_teams
from .sheets_sync import PickOwnership

STYLE = """
:root { color-scheme: light dark; }
body {
  margin: 0; padding: 24px 16px; background: #0f1115; color: #e8e8ea;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
}
@media (prefers-color-scheme: light) {
  body { background: #f7f7f8; color: #1a1a1a; }
  table { background: #fff; }
  th { background: #eee; }
  tr:nth-child(even) { background: #f2f2f2; }
  .card { background: #fff; border-color: #ddd; }
}
h1 { font-size: 1.5rem; margin-bottom: 0.1em; }
.subtitle { opacity: 0.7; margin-bottom: 1.5em; font-size: 0.9rem; }
.card {
  max-width: 900px; margin: 0 auto 24px auto; background: #1a1d24;
  border: 1px solid #2a2d35; border-radius: 10px; padding: 16px 20px;
  overflow-x: auto;
}
h2 { font-size: 1.1rem; margin-top: 0; }
table { border-collapse: collapse; width: 100%; font-size: 0.92rem; }
th, td { text-align: left; padding: 6px 10px; border-bottom: 1px solid rgba(128,128,128,0.25); }
th { background: rgba(128,128,128,0.15); }
tr:nth-child(even) { background: rgba(128,128,128,0.06); }
.eliminated { opacity: 0.5; text-decoration: line-through; }
.lives-2 { color: #4caf50; }
.lives-1 { color: #ffb300; }
.lives-0 { color: #e05252; }
.wrap { max-width: 900px; margin: 0 auto; }
"""


def _esc(value) -> str:
    return html.escape(str(value)) if value is not None else ""


def _lives_class(lives: int) -> str:
    return f"lives-{max(0, min(2, lives))}"


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

    entries = conn.execute(
        "SELECT * FROM lp_entry ORDER BY eliminated ASC, lives_remaining DESC, display_name ASC"
    ).fetchall()

    standings_rows = []
    for e in entries:
        used = sorted(used_teams(conn, e["id"], season_year))
        status = f"OUT (wk {e['eliminated_week']})" if e["eliminated"] else f"{e['lives_remaining']} live(s)"
        row_class = "eliminated" if e["eliminated"] else _lives_class(e["lives_remaining"])
        standings_rows.append(
            f"<tr class='{row_class}'><td>{_esc(e['display_name'])}</td><td>{_esc(status)}</td>"
            f"<td>{_esc(', '.join(used) or '—')}</td></tr>"
        )

    ownership_html = ""
    if ownership:
        rows = "".join(
            f"<tr><td>{_esc(o.team)}</td><td>{o.count}</td>"
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

    my_entries = [e for e in entries if e["is_mine"] and not e["eliminated"]]
    my_html_parts = []
    for e in my_entries:
        recs = recommend_week(conn, season_year, week_number, e["id"])
        if not recs:
            my_html_parts.append(f"<h3>{_esc(e['display_name'])}</h3><p>No available teams with a game this week.</p>")
            continue
        rows = "".join(
            f"<tr><td>{_esc(r.team)}</td><td>{'home' if r.is_home else 'away'} vs {_esc(r.opponent)}</td>"
            f"<td>{r.p_lose:.1%}</td></tr>"
            for r in recs[:8]
        )
        my_html_parts.append(
            f"<h3>{_esc(e['display_name'])} ({e['lives_remaining']} live(s))</h3>"
            f"<table><tr><th>Team</th><th>Matchup</th><th>P(loses)</th></tr>{rows}</table>"
        )
    my_html = (
        f"<div class='card'><h2>This week's recommendations</h2>{''.join(my_html_parts)}</div>"
        if my_html_parts else ""
    )

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
<h1>Loser Pool {season_year} — Week {week_number}</h1>
<div class="subtitle">Last updated {generated_at.strftime('%Y-%m-%d %H:%M UTC')}</div>

<div class="card">
  <h2>Standings</h2>
  <table>
    <tr><th>Entry</th><th>Status</th><th>Used teams</th></tr>
    {''.join(standings_rows)}
  </table>
</div>

{ownership_html}
{my_html}
</div>
</body>
</html>
"""
