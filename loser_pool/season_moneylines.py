"""Parses a season-long moneyline table (one row per team, one column per
week — "Team,wk1,wk2,...,wk18" CSV, each cell "{moneyline} {loc}{opp}" /
"TBD {loc}{opp}" / "BYE") and bulk-imports it as win probabilities.

Why moneylines instead of point spreads (season_spreads.py): this table
gives BOTH teams' own line for the same game each week (their own row),
so a real vig-free ("devigged") win probability can be computed — convert
each side's American-odds moneyline to its raw implied probability, then
normalize the pair to sum to 1. That's more accurate than reading a point
spread off just one side. The result is still stored through the existing
favorite/spread_margin columns (converted to an equivalent point spread
via the same normal-CDF margin model spread_model.py already uses), so
every other part of this tool — ratings, the optimizer, the outlook
views, the dashboard — needs no changes to consume it.

Same non-clobbering rule as season_spreads.py: a real market spread
sync-week already fetched always wins, and only a game still on its own
earlier projection (this importer's or season_spreads.py's) gets
refreshed by a re-import — tracked via spread_source, same pattern.
"""
from __future__ import annotations

import csv
import io
import sqlite3
from dataclasses import dataclass
from statistics import NormalDist
from typing import Dict, List, Optional, Tuple

from . import db
from .config import LoserPoolConfig
from .teams import resolve_team

MONEYLINE_SOURCE_LABEL = "season-long moneyline projection (pasted)"

_EPS = 1e-6


def moneyline_to_prob(moneyline: float) -> float:
    """Raw (vig-included) implied win probability from American odds."""
    if moneyline < 0:
        return (-moneyline) / (-moneyline + 100.0)
    return 100.0 / (moneyline + 100.0)


@dataclass
class GridMoneyline:
    week_number: int
    team: str
    opponent: Optional[str]  # None for a bye week
    team_is_home: Optional[bool]
    moneyline: Optional[float]  # None for a bye week OR a "TBD" line


def parse_moneyline_grid(text: str) -> List[GridMoneyline]:
    reader = csv.reader(io.StringIO(text))
    rows = [r for r in reader if r and r[0].strip()]
    if not rows:
        return []
    header = rows[0]
    week_numbers = []
    for col in header[1:]:
        try:
            week_numbers.append(int(col.strip()))
        except ValueError:
            week_numbers.append(None)

    out: List[GridMoneyline] = []
    for row in rows[1:]:
        team = resolve_team(row[0])
        for week_number, cell in zip(week_numbers, row[1:]):
            if week_number is None:
                continue
            cell = cell.strip()
            if not cell or cell.upper() == "BYE":
                out.append(GridMoneyline(week_number, team, None, None, None))
                continue

            parts = cell.split(None, 1)
            if len(parts) != 2:
                continue  # malformed cell — skip rather than guess
            ml_token, loc_opp = parts
            loc_opp = loc_opp.strip()
            if loc_opp.upper().startswith("VS"):
                team_is_home, opp_token = True, loc_opp[2:]
            elif loc_opp.startswith("@"):
                team_is_home, opp_token = False, loc_opp[1:]
            else:
                continue  # unrecognized location marker — skip rather than guess
            opponent = resolve_team(opp_token.strip())

            moneyline = None
            if ml_token.upper() != "TBD":
                try:
                    moneyline = float(ml_token)
                except ValueError:
                    moneyline = None

            out.append(GridMoneyline(week_number, team, opponent, team_is_home, moneyline))
    return out


@dataclass
class ImportReport:
    written: int = 0
    skipped_bye: int = 0
    skipped_no_line_yet: int = 0
    skipped_market_data_present: int = 0
    skipped_orientation_conflict: int = 0


def import_moneyline_grid(
    conn: sqlite3.Connection, season_year: int, text: str, cfg: Optional[LoserPoolConfig] = None
) -> ImportReport:
    cfg = cfg or LoserPoolConfig.load(conn)
    report = ImportReport()
    entries = parse_moneyline_grid(text)

    # Index every real (non-TBD, non-bye) line by (week, team) so each row
    # can look up its opponent's own line for the same game, to devig.
    lines_by_week_team: Dict[Tuple[int, str], float] = {
        (e.week_number, e.team): e.moneyline for e in entries if e.moneyline is not None
    }

    for e in entries:
        if e.opponent is None:
            report.skipped_bye += 1
            continue
        if e.moneyline is None:
            report.skipped_no_line_yet += 1
            continue

        p_team_raw = moneyline_to_prob(e.moneyline)
        opponent_ml = lines_by_week_team.get((e.week_number, e.opponent))
        if opponent_ml is not None:
            p_opp_raw = moneyline_to_prob(opponent_ml)
            p_team = p_team_raw / (p_team_raw + p_opp_raw)  # devigged
        else:
            p_team = p_team_raw  # no opposing line yet — best available estimate

        p_home = p_team if e.team_is_home else 1.0 - p_team
        p_home = min(max(p_home, _EPS), 1.0 - _EPS)
        signed_home_spread = cfg.margin_std_dev * NormalDist().inv_cdf(p_home)

        if signed_home_spread > 0:
            favorite, margin = "home", signed_home_spread
        elif signed_home_spread < 0:
            favorite, margin = "away", -signed_home_spread
        else:
            favorite, margin = None, 0.0

        home_team, away_team = (e.team, e.opponent) if e.team_is_home else (e.opponent, e.team)

        week_id = db.get_or_create_week(conn, season_year, e.week_number)
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
            WHERE id = ? AND (spread_source IS NULL OR spread_source IN (?, ?))
            """,
            (favorite, margin, MONEYLINE_SOURCE_LABEL, game_id, MONEYLINE_SOURCE_LABEL,
             "season-long projection (pasted)"),
        )
        if cur.rowcount:
            report.written += 1
        else:
            report.skipped_market_data_present += 1

    conn.commit()
    return report
