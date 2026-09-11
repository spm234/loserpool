"""Ties together schedule discovery, spread/result fetching, and
settlement for one week — the single call the automated refresh workflow
makes each run, instead of the CLI's one-game-at-a-time fetch commands.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import List, Optional

from . import db, live_data
from .config import LoserPoolConfig
from .picks import SettleResult, settle_week


@dataclass
class SyncReport:
    games_discovered: int = 0
    spreads_recorded: int = 0
    results_recorded: int = 0
    settled: List[SettleResult] = field(default_factory=list)
    fetch_errors: List[str] = field(default_factory=list)


def sync_week(
    conn: sqlite3.Connection,
    season_year: int,
    week_number: int,
    *,
    cfg: Optional[LoserPoolConfig] = None,
    api_key: Optional[str] = None,
    also_settle_week: Optional[int] = None,
) -> SyncReport:
    """Discovers this week's games from whatever's currently on the Odds
    API board (matched to `week_number` by kickoff date), records any
    posted spreads, fetches final scores for games that have finished,
    then settles every pending pick this data resolves. `also_settle_week`
    re-runs settlement for one more week (e.g. last week, in case a result
    landed late) without re-discovering its schedule.
    """
    cfg = cfg or LoserPoolConfig.load(conn)
    report = SyncReport()

    week1_date = None
    if cfg.season_week1_date:
        from .season_calendar import parse_iso_date, week_number_for_date
        week1_date = parse_iso_date(cfg.season_week1_date)

    try:
        events = live_data.list_board_events(api_key=api_key)
    except live_data.LiveDataError as e:
        report.fetch_errors.append(f"could not list board events: {e}")
        events = []

    for event in events:
        if week1_date is not None:
            from .season_calendar import week_number_for_date
            event_week = week_number_for_date(week1_date, event.commence_time.date())
            if event_week != week_number:
                continue

        week_id = db.get_or_create_week(conn, season_year, week_number)
        db.get_or_create_game(conn, week_id, event.away_team, event.home_team)
        conn.commit()
        report.games_discovered += 1

        if event.favorite is not None:
            from . import importer
            favorite = None if event.favorite == "even" else event.favorite
            importer.record_game_result(
                conn, season_year, week_number, event.away_team, event.home_team,
                favorite=favorite, margin=event.margin, spread_source=event.source,
            )
            report.spreads_recorded += 1

    week_id = db.get_or_create_week(conn, season_year, week_number)
    games = conn.execute("SELECT away_team, home_team, outcome FROM lp_game WHERE week_id = ?", (week_id,)).fetchall()
    for game in games:
        if game["outcome"] is not None:
            continue
        try:
            live_data.fetch_and_save_result(
                conn, season_year, week_number, game["away_team"], game["home_team"], api_key=api_key
            )
            report.results_recorded += 1
        except live_data.LiveDataError:
            continue  # not finished yet (or not found) — fine, try again next run

    report.settled.extend(settle_week(conn, season_year, week_number, cfg))
    if also_settle_week is not None:
        report.settled.extend(settle_week(conn, season_year, also_settle_week, cfg))

    return report
