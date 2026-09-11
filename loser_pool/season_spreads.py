"""Parses a full-season "team x week" spread grid — one row per team, one
cell per week showing that team's spread and opponent/location — into
individual game records, and bulk-imports them. This is the shape of a
typical season-long-odds page.

Why this exists: The Odds API only shows its near-term board (see
live_data.list_board_events), so on its own this tool only learns a
week's schedule once it's close enough to have real market odds — the
league-wide outlook views (team_outlook.py) are correspondingly thin
early in the season. A full projected season lets those views work across
the whole season immediately. This data isn't available from anywhere
this tool can fetch on its own (clevanalytics.com, the obvious source, is
blocked by this environment's network policy — see README), so it's a
paste-based import like everything else here: refresh it occasionally as
projections move, and real market data always wins once it exists — see
import_season_spread_grid's docstring for how that's enforced.

**Grid text shape**: one row per team, starting with a team code (any of
the 32 sportsbook-style abbreviations in teams.SPORTSBOOK_ABBRS — ARI,
ATL, BAL, ...), followed by up to 18 week-cells in order, each either:
  - a single line "—" (or "-", "--", "BYE") for a bye week, or
  - two lines: a spread ("+11.5", "-3.5", or "PK") **relative to that
    team** (positive = that team is the underdog by this many points),
    then a location+opponent line ("@ LAC" or "vs SEA").
Blank lines and anything before the first recognized team-code line
(e.g. a header row) are ignored.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import List, Optional

from . import db
from .teams import SPORTSBOOK_ABBRS, resolve_team

PROJECTION_SOURCE_LABEL = "season-long projection (pasted)"


@dataclass
class GridGame:
    week_number: int
    team: str
    opponent: Optional[str]  # None for a bye week
    team_is_home: Optional[bool]  # None for a bye week
    team_spread: Optional[float]  # None for a bye week; + = team is the underdog


def parse_season_spread_grid(text: str) -> List[GridGame]:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    games: List[GridGame] = []
    current_team: Optional[str] = None
    week = 0
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.upper() in SPORTSBOOK_ABBRS:
            current_team = resolve_team(line.upper())
            week = 0
            i += 1
            continue
        if current_team is None:
            i += 1  # header row or other junk before the first team
            continue

        week += 1
        if line in ("—", "-", "--", "BYE"):
            games.append(GridGame(week, current_team, None, None, None))
            i += 1
            continue

        if i + 1 >= len(lines):
            break  # malformed trailing row — stop rather than guess
        loc_line = lines[i + 1]
        loc, _, opp_token = loc_line.partition(" ")
        team_is_home = loc.strip().lower() == "vs"
        opponent = resolve_team(opp_token.strip())
        team_spread = 0.0 if line.upper() == "PK" else float(line)
        games.append(GridGame(week, current_team, opponent, team_is_home, team_spread))
        i += 2

    return games


@dataclass
class ImportReport:
    written: int = 0
    skipped_bye: int = 0
    skipped_market_data_present: int = 0
    skipped_orientation_conflict: int = 0


def import_season_spread_grid(conn: sqlite3.Connection, season_year: int, text: str) -> ImportReport:
    """Writes each parsed game's projected spread, EXCEPT where a real
    market spread already exists for it (spread_source not NULL and not
    this function's own label) — a season-long projection should never
    clobber an actual line sync-week already fetched. Re-running this
    with an updated grid DOES refresh a game still on its own earlier
    projection, so periodic re-pastes as the projection moves stay useful.
    """
    report = ImportReport()
    for g in parse_season_spread_grid(text):
        if g.team_spread is None:
            report.skipped_bye += 1
            continue

        if g.team_is_home:
            home_team, away_team = g.team, g.opponent
            side_favored_if_positive, side_favored_if_negative = "away", "home"
        else:
            away_team, home_team = g.team, g.opponent
            side_favored_if_positive, side_favored_if_negative = "home", "away"

        if g.team_spread > 0:
            favorite, margin = side_favored_if_positive, g.team_spread
        elif g.team_spread < 0:
            favorite, margin = side_favored_if_negative, -g.team_spread
        else:
            favorite, margin = None, 0.0

        week_id = db.get_or_create_week(conn, season_year, g.week_number)

        # The grid gives each game's home/away from BOTH teams' own rows.
        # If they disagree (a transcription slip in the source, or in this
        # game's own row vs. the opponent's row elsewhere in the grid) and
        # a game between these same two teams already exists this week
        # under the OPPOSITE orientation, that's the same real game — skip
        # rather than create a second, conflicting game record for it.
        conflicting = conn.execute(
            "SELECT id FROM lp_game WHERE week_id = ? AND away_team = ? AND home_team = ?",
            (week_id, home_team, away_team),
        ).fetchone()
        if conflicting:
            report.skipped_orientation_conflict += 1
            continue

        game_id = db.get_or_create_game(conn, week_id, away_team, home_team)
        cur = conn.execute(
            """
            UPDATE lp_game SET favorite = ?, spread_margin = ?, spread_source = ?
            WHERE id = ? AND (spread_source IS NULL OR spread_source = ?)
            """,
            (favorite, margin, PROJECTION_SOURCE_LABEL, game_id, PROJECTION_SOURCE_LABEL),
        )
        if cur.rowcount:
            report.written += 1
        else:
            report.skipped_market_data_present += 1

    conn.commit()
    return report
