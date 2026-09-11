"""Data for one team's page: its full known schedule with per-game loss
probability, who has picked it and how that turned out, and its actual
on-field record so far. Pure data gathering — export_html.py renders it.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import List, Optional

from .config import LoserPoolConfig
from .ratings import game_win_probabilities, get_team_rating
from .teams import ALL_NICKNAMES, resolve_team


@dataclass
class ScheduleRow:
    week_number: int
    opponent: str
    is_home: bool
    p_lose: float
    outcome: Optional[str]  # 'win' | 'loss' | 'tie' | None (not played yet)
    home_score: Optional[int]
    away_score: Optional[int]


@dataclass
class PickerRow:
    entry_name: str
    week_number: int
    result: str  # 'pending' | 'survived' | 'busted'


def team_schedule(
    conn: sqlite3.Connection, season_year: int, team: str, cfg: Optional[LoserPoolConfig] = None
) -> List[ScheduleRow]:
    """Every known game for `team` this season, in week order."""
    cfg = cfg or LoserPoolConfig.load(conn)
    team = resolve_team(team)
    rows = conn.execute(
        """
        SELECT g.*, w.week_number
        FROM lp_game g
        JOIN lp_week w ON w.id = g.week_id
        WHERE w.season_year = ? AND (g.away_team = ? OR g.home_team = ?)
        ORDER BY w.week_number
        """,
        (season_year, team, team),
    ).fetchall()

    out = []
    for g in rows:
        is_home = g["home_team"] == team
        opponent = g["away_team"] if is_home else g["home_team"]
        p_home_win, p_away_win = game_win_probabilities(conn, g, season_year, g["week_number"], cfg)
        p_team_win = p_home_win if is_home else p_away_win
        p_lose = 1.0 - p_team_win

        outcome = None
        if g["outcome"] == "tie":
            outcome = "tie"
        elif g["outcome"] is not None:
            team_side = "home" if is_home else "away"
            outcome = "win" if g["outcome"] == team_side else "loss"

        out.append(
            ScheduleRow(
                week_number=g["week_number"],
                opponent=opponent,
                is_home=is_home,
                p_lose=p_lose,
                outcome=outcome,
                home_score=g["home_score"],
                away_score=g["away_score"],
            )
        )
    return out


def team_record(rows: List[ScheduleRow]) -> str:
    wins = sum(1 for r in rows if r.outcome == "win")
    losses = sum(1 for r in rows if r.outcome == "loss")
    ties = sum(1 for r in rows if r.outcome == "tie")
    return f"{wins}-{losses}-{ties}" if ties else f"{wins}-{losses}"


def team_pickers(conn: sqlite3.Connection, season_year: int, team: str) -> List[PickerRow]:
    """Every entry that has ever picked `team` this season, across all
    weeks (including before a playoff reset, if any — this is informational
    history, not a used-team check, so it isn't filtered to the current
    reset cycle the way picks.used_teams is).
    """
    team = resolve_team(team)
    rows = conn.execute(
        """
        SELECT e.display_name, w.week_number, p.result
        FROM lp_pick p
        JOIN lp_entry e ON e.id = p.entry_id
        JOIN lp_week w ON w.id = p.week_id
        WHERE w.season_year = ? AND p.team_picked = ?
        ORDER BY w.week_number, e.display_name
        """,
        (season_year, team),
    ).fetchall()
    return [PickerRow(r["display_name"], r["week_number"], r["result"]) for r in rows]


def current_elo_rating(
    conn: sqlite3.Connection, season_year: int, team: str, as_of_week: int, cfg: Optional[LoserPoolConfig] = None
) -> float:
    cfg = cfg or LoserPoolConfig.load(conn)
    return get_team_rating(conn, resolve_team(team), season_year, as_of_week, cfg)


def all_teams_with_pages(conn: sqlite3.Connection, season_year: int) -> List[str]:
    """Every team worth generating a page for: the standard 32 plus
    anything else that's actually shown up in this season's games/picks
    (a typo or a test fixture's fictional team, so pages don't silently
    404 for something the dashboard linked to).
    """
    rows = conn.execute(
        """
        SELECT DISTINCT away_team AS team FROM lp_game g JOIN lp_week w ON w.id = g.week_id WHERE w.season_year = ?
        UNION
        SELECT DISTINCT home_team FROM lp_game g JOIN lp_week w ON w.id = g.week_id WHERE w.season_year = ?
        UNION
        SELECT DISTINCT team_picked FROM lp_pick p JOIN lp_week w ON w.id = p.week_id WHERE w.season_year = ?
        """,
        (season_year, season_year, season_year),
    ).fetchall()
    extra = {r["team"] for r in rows}
    return sorted(set(ALL_NICKNAMES) | extra)
