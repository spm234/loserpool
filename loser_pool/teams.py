"""Canonical NFL team registry: resolves any known alias (full name like
"New England Patriots" or nickname like "Patriots") to one canonical
nickname, and looks up a logo image URL.

Why this matters beyond cosmetics: The Odds API returns full names
("Buffalo Bills"), but the pool's Google Sheet only ever has nicknames
("Bills"). Without normalizing both to the same canonical form, a sheet
pick of "Patriots" would never match a schedule game stored as "New
England Patriots" — record_pick would raise "No game found" for every
single sheet-synced pick once sync-week (Odds API) is what populates the
schedule. db.get_or_create_game() and picks.record_pick() both normalize
through resolve_team() so every write ends up in the same canonical form,
regardless of which source it came from.

Unrecognized names (typos, or the fictional team names used in tests)
pass through resolve_team() unchanged rather than raising — this is a
convenience layer, not a validator.
"""
from __future__ import annotations

from typing import Dict, Optional

# (full name, nickname, ESPN team abbreviation)
_TEAMS = [
    ("Arizona Cardinals", "Cardinals", "ari"),
    ("Atlanta Falcons", "Falcons", "atl"),
    ("Baltimore Ravens", "Ravens", "bal"),
    ("Buffalo Bills", "Bills", "buf"),
    ("Carolina Panthers", "Panthers", "car"),
    ("Chicago Bears", "Bears", "chi"),
    ("Cincinnati Bengals", "Bengals", "cin"),
    ("Cleveland Browns", "Browns", "cle"),
    ("Dallas Cowboys", "Cowboys", "dal"),
    ("Denver Broncos", "Broncos", "den"),
    ("Detroit Lions", "Lions", "det"),
    ("Green Bay Packers", "Packers", "gb"),
    ("Houston Texans", "Texans", "hou"),
    ("Indianapolis Colts", "Colts", "ind"),
    ("Jacksonville Jaguars", "Jaguars", "jax"),
    ("Kansas City Chiefs", "Chiefs", "kc"),
    ("Las Vegas Raiders", "Raiders", "lv"),
    ("Los Angeles Chargers", "Chargers", "lac"),
    ("Los Angeles Rams", "Rams", "lar"),
    ("Miami Dolphins", "Dolphins", "mia"),
    ("Minnesota Vikings", "Vikings", "min"),
    ("New England Patriots", "Patriots", "ne"),
    ("New Orleans Saints", "Saints", "no"),
    ("New York Giants", "Giants", "nyg"),
    ("New York Jets", "Jets", "nyj"),
    ("Philadelphia Eagles", "Eagles", "phi"),
    ("Pittsburgh Steelers", "Steelers", "pit"),
    ("San Francisco 49ers", "49ers", "sf"),
    ("Seattle Seahawks", "Seahawks", "sea"),
    ("Tampa Bay Buccaneers", "Buccaneers", "tb"),
    ("Tennessee Titans", "Titans", "ten"),
    ("Washington Commanders", "Commanders", "wsh"),
]

ALL_NICKNAMES = [nick for _full, nick, _abbr in _TEAMS]

# Common sportsbook/odds-table abbreviations (e.g. as used in a "full season
# spreads" grid), which don't all match ESPN's own codes (WAS vs wsh, GB has
# no ESPN-style 2-letter form here, etc.) — kept separate from _TEAMS' ESPN
# abbreviations (used for logos) since they serve a different purpose:
# recognizing pasted odds-table text, not building image URLs.
_SPORTSBOOK_ABBR_TO_NICKNAME = {
    "ARI": "Cardinals", "ATL": "Falcons", "BAL": "Ravens", "BUF": "Bills",
    "CAR": "Panthers", "CHI": "Bears", "CIN": "Bengals", "CLE": "Browns",
    "DAL": "Cowboys", "DEN": "Broncos", "DET": "Lions", "GB": "Packers",
    "HOU": "Texans", "IND": "Colts", "JAX": "Jaguars", "KC": "Chiefs",
    "LAC": "Chargers", "LAR": "Rams", "LV": "Raiders", "MIA": "Dolphins",
    "MIN": "Vikings", "NE": "Patriots", "NO": "Saints", "NYG": "Giants",
    "NYJ": "Jets", "PHI": "Eagles", "PIT": "Steelers", "SEA": "Seahawks",
    "SF": "49ers", "TB": "Buccaneers", "TEN": "Titans", "WAS": "Commanders",
}

_ALIAS_TO_NICKNAME: Dict[str, str] = {}
_NICKNAME_TO_ABBR: Dict[str, str] = {}
for _full, _nick, _abbr in _TEAMS:
    _ALIAS_TO_NICKNAME[_full.lower()] = _nick
    _ALIAS_TO_NICKNAME[_nick.lower()] = _nick
    _NICKNAME_TO_ABBR[_nick] = _abbr
for _sb_abbr, _nick in _SPORTSBOOK_ABBR_TO_NICKNAME.items():
    _ALIAS_TO_NICKNAME.setdefault(_sb_abbr.lower(), _nick)

SPORTSBOOK_ABBRS = set(_SPORTSBOOK_ABBR_TO_NICKNAME.keys())

LOGO_URL_TEMPLATE = "https://a.espncdn.com/i/teamlogos/nfl/500/{abbr}.png"


def resolve_team(name: str) -> str:
    """Normalizes a full name or nickname to the canonical nickname.
    Anything unrecognized (typo, or a test fixture's fictional team name)
    passes through unchanged, stripped of surrounding whitespace.
    """
    if name is None:
        return name
    stripped = name.strip()
    return _ALIAS_TO_NICKNAME.get(stripped.lower(), stripped)


def abbr_for(name: str) -> Optional[str]:
    return _NICKNAME_TO_ABBR.get(resolve_team(name))


def logo_url(name: str) -> Optional[str]:
    abbr = abbr_for(name)
    return LOGO_URL_TEMPLATE.format(abbr=abbr) if abbr else None
