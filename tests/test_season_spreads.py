import pytest

from loser_pool import db, importer
from loser_pool.season_spreads import (
    PROJECTION_SOURCE_LABEL,
    import_season_spread_grid,
    parse_season_spread_grid,
)

SAMPLE_GRID = """Team\tW1\tW2
ARI
+11.5
@ LAC
-3.0
vs SEA
LAC
-11.5
vs ARI
—
"""


@pytest.fixture
def conn(tmp_path):
    db_path = tmp_path / "test.db"
    db.init_db(db_path)
    c = db.connect(db_path)
    yield c
    c.close()


def test_parse_season_spread_grid_basic():
    games = parse_season_spread_grid(SAMPLE_GRID)
    assert len(games) == 4
    ari_wk1 = games[0]
    assert ari_wk1.team == "Cardinals"
    assert ari_wk1.opponent == "Chargers"
    assert ari_wk1.team_is_home is False
    assert ari_wk1.team_spread == 11.5


def test_parse_season_spread_grid_bye_week():
    games = parse_season_spread_grid(SAMPLE_GRID)
    lac_wk2 = games[3]
    assert lac_wk2.team == "Chargers"
    assert lac_wk2.week_number == 2
    assert lac_wk2.team_spread is None
    assert lac_wk2.opponent is None


def test_parse_season_spread_grid_pk_is_zero():
    text = "ARI\nPK\n@ LAC\n"
    games = parse_season_spread_grid(text)
    assert games[0].team_spread == 0.0


def test_parse_season_spread_grid_ignores_header_and_blank_lines():
    text = "Team\tW1\tW2\n\nARI\n+11.5\n@ LAC\n\n\n-3.0\nvs SEA\n"
    games = parse_season_spread_grid(text)
    assert len(games) == 2
    assert games[0].week_number == 1
    assert games[1].week_number == 2


def test_import_season_spread_grid_derives_correct_favorite_and_margin(conn):
    import_season_spread_grid(conn, 2026, SAMPLE_GRID)
    week_id = db.get_or_create_week(conn, 2026, 1)
    game = conn.execute(
        "SELECT * FROM lp_game WHERE week_id = ? AND away_team = 'Cardinals' AND home_team = 'Chargers'",
        (week_id,),
    ).fetchone()
    assert game["favorite"] == "home"  # Chargers favored (Cardinals are the +11.5 underdog)
    assert game["spread_margin"] == 11.5
    assert game["spread_source"] == PROJECTION_SOURCE_LABEL


def test_import_season_spread_grid_home_favorite_case(conn):
    import_season_spread_grid(conn, 2026, SAMPLE_GRID)
    week_id = db.get_or_create_week(conn, 2026, 2)
    game = conn.execute(
        "SELECT * FROM lp_game WHERE week_id = ? AND away_team = 'Seahawks' AND home_team = 'Cardinals'",
        (week_id,),
    ).fetchone()
    assert game["favorite"] == "home"  # Cardinals -3.0 at home
    assert game["spread_margin"] == 3.0


def test_import_season_spread_grid_skips_bye_weeks(conn):
    report = import_season_spread_grid(conn, 2026, SAMPLE_GRID)
    assert report.skipped_bye == 1


def test_import_season_spread_grid_never_overwrites_real_market_data(conn):
    # A real market spread already recorded (e.g. by sync-week) for this game.
    importer.record_game_result(
        conn, 2026, 1, "Cardinals", "Chargers", favorite="away", margin=2.0, spread_source="The Odds API, median of 9 books",
    )
    report = import_season_spread_grid(conn, 2026, SAMPLE_GRID)
    week_id = db.get_or_create_week(conn, 2026, 1)
    game = conn.execute(
        "SELECT * FROM lp_game WHERE week_id = ? AND away_team = 'Cardinals' AND home_team = 'Chargers'",
        (week_id,),
    ).fetchone()
    assert game["favorite"] == "away"
    assert game["spread_margin"] == 2.0
    assert game["spread_source"] == "The Odds API, median of 9 books"
    assert report.skipped_market_data_present >= 1


def test_import_season_spread_grid_refreshes_its_own_earlier_projection(conn):
    import_season_spread_grid(conn, 2026, SAMPLE_GRID)
    updated_grid = SAMPLE_GRID.replace("+11.5", "+9.0").replace("-11.5", "-9.0")
    import_season_spread_grid(conn, 2026, updated_grid)
    week_id = db.get_or_create_week(conn, 2026, 1)
    game = conn.execute(
        "SELECT * FROM lp_game WHERE week_id = ? AND away_team = 'Cardinals' AND home_team = 'Chargers'",
        (week_id,),
    ).fetchone()
    assert game["spread_margin"] == 9.0
