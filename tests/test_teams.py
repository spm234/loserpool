from loser_pool.teams import abbr_for, logo_url, resolve_team


def test_resolve_team_full_name_to_nickname():
    assert resolve_team("New England Patriots") == "Patriots"


def test_resolve_team_nickname_is_passthrough():
    assert resolve_team("Patriots") == "Patriots"


def test_resolve_team_case_insensitive():
    assert resolve_team("new england patriots") == "Patriots"


def test_resolve_team_strips_whitespace():
    assert resolve_team("  Patriots  ") == "Patriots"


def test_resolve_team_unrecognized_passes_through_stripped():
    assert resolve_team(" TeamA ") == "TeamA"


def test_abbr_for_known_team():
    assert abbr_for("New England Patriots") == "ne"
    assert abbr_for("49ers") == "sf"


def test_abbr_for_unknown_team_is_none():
    assert abbr_for("TeamA") is None


def test_logo_url_known_and_unknown():
    assert logo_url("Patriots") == "https://a.espncdn.com/i/teamlogos/nfl/500/ne.png"
    assert logo_url("TeamA") is None
