"""League-wide (not entry-specific) views: how often each team has been
used so far, which weeks each team projects as the biggest underdog, and
which team is the single biggest underdog in each week. Unlike
optimizer.py/simulation.py, nothing here excludes already-used teams or
accounts for anyone's lives — this is "what does the slate look like",
not "what should I pick".
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Dict, List, Optional

from . import db
from .config import LoserPoolConfig
from .matchups import TeamWeekOption, week_options_for_entry
from .teams import ALL_NICKNAMES


@dataclass
class TeamUsage:
    team: str
    times_picked: int


def season_to_date_team_usage(conn: sqlite3.Connection, season_year: int) -> List[TeamUsage]:
    """How many distinct entries have picked each team so far this cycle
    (i.e. since the last playoff reset, same boundary picks.used_teams
    uses) — every one of the 32 teams is included even at zero, so this
    doubles as "what's still wide open". A team can only be picked once
    per entry per season, so this count is also exactly how many entries
    have that team locked in as unavailable going forward.
    """
    reset_week = db.most_recent_reset_week(conn)
    rows = conn.execute(
        """
        SELECT p.team_picked AS team, COUNT(DISTINCT p.entry_id) AS n
        FROM lp_pick p
        JOIN lp_week w ON w.id = p.week_id
        WHERE w.season_year = ? AND w.week_number > ?
        GROUP BY p.team_picked
        """,
        (season_year, reset_week),
    ).fetchall()
    counts = {r["team"]: r["n"] for r in rows}
    # Include any team that shows up in picks but isn't in the standard
    # 32 (a typo, or a fictional test team) too, rather than dropping it.
    all_teams = sorted(set(ALL_NICKNAMES) | set(counts.keys()))
    usage = [TeamUsage(team=t, times_picked=counts.get(t, 0)) for t in all_teams]
    usage.sort(key=lambda u: (-u.times_picked, u.team))
    return usage


def known_weeks(conn: sqlite3.Connection, season_year: int) -> List[int]:
    """Every week number that currently has at least one scheduled game —
    i.e. what this tool actually knows about, not a fixed 18-week window.
    Early season this may only be 1-2 weeks; it grows as sync-week
    discovers more of the schedule over time.
    """
    rows = conn.execute(
        """
        SELECT DISTINCT w.week_number FROM lp_week w
        JOIN lp_game g ON g.week_id = w.id
        WHERE w.season_year = ? AND w.week_number <= 18
        ORDER BY w.week_number
        """,
        (season_year,),
    ).fetchall()
    return [r["week_number"] for r in rows]


def team_week_matrix(
    conn: sqlite3.Connection,
    season_year: int,
    week_numbers: List[int],
    cfg: Optional[LoserPoolConfig] = None,
) -> Dict[str, Dict[int, TeamWeekOption]]:
    """{team: {week_number: TeamWeekOption}} across every team with a game
    in any of `week_numbers` — the full slate, not filtered to any one
    entry's available teams. Reuses matchups.week_options_for_entry with
    an empty exclude set for exactly that reason.
    """
    cfg = cfg or LoserPoolConfig.load(conn)
    options_by_week = week_options_for_entry(conn, season_year, week_numbers, set(), cfg)
    matrix: Dict[str, Dict[int, TeamWeekOption]] = {}
    for week_number, options in options_by_week.items():
        for opt in options:
            matrix.setdefault(opt.team, {})[week_number] = opt
    return matrix


def weekly_biggest_underdogs(
    conn: sqlite3.Connection,
    season_year: int,
    week_numbers: List[int],
    cfg: Optional[LoserPoolConfig] = None,
    top_n: int = 5,
) -> Dict[int, List[TeamWeekOption]]:
    """{week_number: [top_n TeamWeekOptions by loss probability]} — the
    "who's the biggest underdog this week" view, independent of any one
    entry's used-team history.
    """
    cfg = cfg or LoserPoolConfig.load(conn)
    options_by_week = week_options_for_entry(conn, season_year, week_numbers, set(), cfg)
    return {
        week: sorted(options, key=lambda o: o.p_lose, reverse=True)[:top_n]
        for week, options in options_by_week.items()
    }


def best_week_per_team(
    matrix: Dict[str, Dict[int, TeamWeekOption]],
) -> List[TeamWeekOption]:
    """One row per team: its single best (highest loss-probability) week
    among whatever weeks are in the matrix — "when does it make the most
    sense to use them", condensed to one line per team, sorted best-first.
    """
    best = [max(weeks.values(), key=lambda o: o.p_lose) for weeks in matrix.values() if weeks]
    best.sort(key=lambda o: o.p_lose, reverse=True)
    return best
