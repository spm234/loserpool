"""Live spread/result/schedule fetching from The Odds API — a documented,
scriptable lines API (https://the-odds-api.com), not a scrape. Needs a
free-tier API key (THE_ODDS_API_KEY or --api-key).

This is a standalone port of the fetch logic originally written for a
sibling tool (spm234/nfl_pool_bets' pool/live_data.py) — copied rather than
imported across repos, since this is meant to run unattended in GitHub
Actions with no dependency on that other project.

clevanalytics.com (the site this whole tool's approach is modeled on) is
blocked by the sandbox this was originally built in, so power ratings here
come from an Elo model (ratings.py) instead of that site's numbers — see
README.
"""
from __future__ import annotations

import os
import sqlite3
import statistics
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

from . import importer
from .ratings import apply_elo_after_result

ODDS_API_BASE = "https://api.the-odds-api.com/v4/sports/americanfootball_nfl/odds"
SCORES_API_BASE = "https://api.the-odds-api.com/v4/sports/americanfootball_nfl/scores"


@dataclass
class SpreadEstimate:
    favorite: str  # 'home' | 'away' | 'even'
    margin: float
    source: str
    fetched_at: str


@dataclass
class GameResult:
    outcome: str  # 'home' | 'away' | 'tie'
    home_score: int
    away_score: int
    source: str
    fetched_at: str


@dataclass
class BoardEvent:
    """One game currently listed on the Odds API's board, with its kickoff
    time (used by season_calendar to figure out which NFL week it's in)
    and spread if one's posted yet.
    """
    away_team: str
    home_team: str
    commence_time: datetime
    favorite: Optional[str]  # 'home' | 'away' | 'even' | None (no spread posted yet)
    margin: float
    source: str


class LiveDataError(Exception):
    pass


def _normalize(name: str) -> str:
    return name.strip().lower()


def _require_requests():
    try:
        import requests
        return requests
    except ImportError as e:
        raise LiveDataError(
            "The 'requests' package is required for live data fetching. "
            "Install it with: pip install requests"
        ) from e


def _require_api_key(api_key: Optional[str]) -> str:
    key = api_key or os.environ.get("THE_ODDS_API_KEY")
    if not key:
        raise LiveDataError(
            "No API key found. Set THE_ODDS_API_KEY or pass api_key= explicitly. "
            "Sign up at https://the-odds-api.com for a free-tier key."
        )
    return key


def _fetch_odds_events(api_key: Optional[str]) -> List[dict]:
    requests = _require_requests()
    key = _require_api_key(api_key)
    try:
        resp = requests.get(
            ODDS_API_BASE,
            params={"apiKey": key, "regions": "us", "markets": "spreads", "oddsFormat": "american"},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        raise LiveDataError(f"Request to The Odds API failed: {e}") from e


def list_board_events(api_key: Optional[str] = None) -> List[BoardEvent]:
    """Every game currently on the Odds API's NFL board — whatever near-term
    window the API is showing, typically the current + next week or so.
    Used to discover the schedule automatically rather than requiring a
    manual schedule paste every week.
    """
    events = _fetch_odds_events(api_key)
    fetched_at = datetime.now(timezone.utc).isoformat()
    out = []
    for event in events:
        away, home = event.get("away_team", ""), event.get("home_team", "")
        if not away or not home:
            continue
        commence_time = datetime.fromisoformat(event["commence_time"].replace("Z", "+00:00"))

        home_margins: List[float] = []
        for bookmaker in event.get("bookmakers", []):
            for market in bookmaker.get("markets", []):
                if market.get("key") != "spreads":
                    continue
                for outcome in market.get("outcomes", []):
                    if _normalize(outcome.get("name", "")) == _normalize(home):
                        home_margins.append(float(outcome["point"]))

        if not home_margins:
            out.append(BoardEvent(away, home, commence_time, None, 0.0, "The Odds API (no spread posted yet)"))
            continue
        median_home_point = statistics.median(home_margins)
        n_books = len(home_margins)
        if median_home_point == 0:
            out.append(BoardEvent(away, home, commence_time, "even", 0.0, f"The Odds API, median of {n_books} books"))
        elif median_home_point < 0:
            out.append(BoardEvent(away, home, commence_time, "home", abs(median_home_point), f"The Odds API, median of {n_books} books"))
        else:
            out.append(BoardEvent(away, home, commence_time, "away", median_home_point, f"The Odds API, median of {n_books} books"))
    return out


def fetch_spread_estimate(away_team: str, home_team: str, *, api_key: Optional[str] = None) -> SpreadEstimate:
    events = _fetch_odds_events(api_key)
    away_n, home_n = _normalize(away_team), _normalize(home_team)
    match = None
    for event in events:
        if _normalize(event.get("away_team", "")) == away_n and _normalize(event.get("home_team", "")) == home_n:
            match = event
            break
    if match is None:
        raise LiveDataError(
            f"No current odds found for {away_team} @ {home_team}. "
            "Check team-name spelling matches The Odds API's naming, or the game may not be listed yet."
        )

    home_margins: List[float] = []
    for bookmaker in match.get("bookmakers", []):
        for market in bookmaker.get("markets", []):
            if market.get("key") != "spreads":
                continue
            for outcome in market.get("outcomes", []):
                if _normalize(outcome.get("name", "")) == home_n:
                    home_margins.append(float(outcome["point"]))

    if not home_margins:
        raise LiveDataError(f"Odds data found for {away_team} @ {home_team} but no spread market present.")

    median_home_point = statistics.median(home_margins)
    fetched_at = datetime.now(timezone.utc).isoformat()
    n_books = len(home_margins)
    if median_home_point == 0:
        return SpreadEstimate("even", 0, f"The Odds API, median of {n_books} books", fetched_at)
    if median_home_point < 0:
        return SpreadEstimate("home", abs(median_home_point), f"The Odds API, median of {n_books} books", fetched_at)
    return SpreadEstimate("away", median_home_point, f"The Odds API, median of {n_books} books", fetched_at)


def fetch_completed_score(
    away_team: str, home_team: str, *, api_key: Optional[str] = None, days_from: int = 3
) -> GameResult:
    """Caveat: this endpoint reports only the final score (after any
    overtime), not the score at the end of regulation.
    """
    requests = _require_requests()
    key = _require_api_key(api_key)
    try:
        resp = requests.get(SCORES_API_BASE, params={"apiKey": key, "daysFrom": days_from}, timeout=15)
        resp.raise_for_status()
        events = resp.json()
    except requests.RequestException as e:
        raise LiveDataError(f"Request to The Odds API failed: {e}") from e

    away_n, home_n = _normalize(away_team), _normalize(home_team)
    match = None
    for event in events:
        if _normalize(event.get("away_team", "")) == away_n and _normalize(event.get("home_team", "")) == home_n:
            match = event
            break
    if match is None:
        raise LiveDataError(
            f"No score data found for {away_team} @ {home_team} in the last {days_from} day(s). "
            "Check team-name spelling, or the game may not have been played yet."
        )
    if not match.get("completed"):
        raise LiveDataError(f"{away_team} @ {home_team} is not marked completed yet.")

    scores = {_normalize(s["name"]): int(s["score"]) for s in match.get("scores") or []}
    if away_n not in scores or home_n not in scores:
        raise LiveDataError(f"Game marked completed but score data is incomplete for {away_team} @ {home_team}.")
    away_score, home_score = scores[away_n], scores[home_n]
    fetched_at = datetime.now(timezone.utc).isoformat()

    if away_score == home_score:
        outcome = "tie"
    elif home_score > away_score:
        outcome = "home"
    else:
        outcome = "away"
    return GameResult(outcome=outcome, home_score=home_score, away_score=away_score, source="The Odds API", fetched_at=fetched_at)


def fetch_and_save_spread(
    conn: sqlite3.Connection,
    season_year: int,
    week_number: int,
    away_team: str,
    home_team: str,
    *,
    api_key: Optional[str] = None,
):
    estimate = fetch_spread_estimate(away_team, home_team, api_key=api_key)
    favorite = None if estimate.favorite == "even" else estimate.favorite
    importer.record_game_result(
        conn, season_year, week_number, away_team, home_team,
        favorite=favorite, margin=estimate.margin, spread_source=estimate.source,
    )
    return estimate


def fetch_and_save_result(
    conn: sqlite3.Connection,
    season_year: int,
    week_number: int,
    away_team: str,
    home_team: str,
    *,
    api_key: Optional[str] = None,
):
    result = fetch_completed_score(away_team, home_team, api_key=api_key)
    importer.record_game_result(
        conn, season_year, week_number, away_team, home_team,
        outcome=result.outcome, home_score=result.home_score, away_score=result.away_score,
    )
    apply_elo_after_result(conn, season_year, week_number, away_team, home_team)
    return result
