"""Maps a calendar date to an NFL regular-season week number, so the
automated refresh workflow can figure out "what week is it" without a
human passing --week by hand every run.

Deliberately regular-season-only (weeks 1-18). NFL playoff weeks don't
follow a flat 7-day cadence (there's a bye week built in before the Super
Bowl), so guessing a playoff week number from a date is more likely to be
wrong than useful — pass --week explicitly once the playoffs start, same
as the sibling nfl_pool_bets tool already documents for its own
week-number math.
"""
from __future__ import annotations

from datetime import date, timedelta

REGULAR_SEASON_WEEKS = 18


def week_number_for_date(week1_start: date, target: date, max_week: int = REGULAR_SEASON_WEEKS) -> int:
    """week1_start is the first day of the Week 1 game window (the Tuesday
    before the season-opening game is the safe choice, so the whole
    Tue-Mon window counts as week 1). Dates before week1_start clamp to
    week 1; dates past the regular season clamp to `max_week` (18) rather
    than guessing at a playoff week number — see module docstring.
    """
    days = (target - week1_start).days
    if days < 0:
        return 1
    return min(days // 7 + 1, max_week)


def parse_iso_date(value: str) -> date:
    return date.fromisoformat(value)
