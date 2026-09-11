import math

import pytest

from loser_pool import db, importer
from loser_pool.season_moneylines import (
    MONEYLINE_SOURCE_LABEL,
    import_moneyline_grid,
    moneyline_to_prob,
    parse_moneyline_grid,
)

SAMPLE_GRID = (
    "Week,1,2\n"
    "Arizona Cardinals,+380  @LAC,TBD  VS SEA\n"
    "Los Angeles Chargers,-500  VS ARI,BYE\n"
    "Seattle Seahawks,-166  @ARI,BYE\n"
)


@pytest.fixture
def conn(tmp_path):
    db_path = tmp_path / "test.db"
    db.init_db(db_path)
    c = db.connect(db_path)
    yield c
    c.close()


def test_moneyline_to_prob_favorite_and_underdog():
    assert moneyline_to_prob(-500) == pytest.approx(500 / 600)
    assert moneyline_to_prob(380) == pytest.approx(100 / 480)


def test_parse_moneyline_grid_basic():
    entries = parse_moneyline_grid(SAMPLE_GRID)
    ari_wk1 = next(e for e in entries if e.team == "Cardinals" and e.week_number == 1)
    assert ari_wk1.opponent == "Chargers"
    assert ari_wk1.team_is_home is False
    assert ari_wk1.moneyline == 380


def test_parse_moneyline_grid_tbd_is_none_moneyline_but_has_opponent():
    entries = parse_moneyline_grid(SAMPLE_GRID)
    ari_wk2 = next(e for e in entries if e.team == "Cardinals" and e.week_number == 2)
    assert ari_wk2.opponent == "Seahawks"
    assert ari_wk2.team_is_home is True
    assert ari_wk2.moneyline is None


def test_parse_moneyline_grid_bye():
    entries = parse_moneyline_grid(SAMPLE_GRID)
    lac_wk2 = next(e for e in entries if e.team == "Chargers" and e.week_number == 2)
    assert lac_wk2.opponent is None
    assert lac_wk2.moneyline is None


def test_import_moneyline_grid_devigs_using_both_sides(conn):
    import_moneyline_grid(conn, 2026, SAMPLE_GRID)
    week_id = db.get_or_create_week(conn, 2026, 1)
    game = conn.execute(
        "SELECT * FROM lp_game WHERE week_id = ? AND away_team = 'Cardinals' AND home_team = 'Chargers'",
        (week_id,),
    ).fetchone()
    assert game["favorite"] == "home"  # Chargers heavily favored (-500)
    assert game["spread_margin"] > 0
    assert game["spread_source"] == MONEYLINE_SOURCE_LABEL

    # Sanity: -500 vs +380 devigged should land Chargers around 80-85% to win.
    from loser_pool.spread_model import win_prob_from_spread
    p_home, _ = win_prob_from_spread(game["spread_margin"], game["favorite"], 13.86)
    assert 0.75 < p_home < 0.90


def test_import_moneyline_grid_skips_tbd_lines(conn):
    report = import_moneyline_grid(conn, 2026, SAMPLE_GRID)
    assert report.skipped_no_line_yet >= 1


def test_import_moneyline_grid_skips_byes(conn):
    report = import_moneyline_grid(conn, 2026, SAMPLE_GRID)
    assert report.skipped_bye >= 1


def test_import_moneyline_grid_never_overwrites_real_market_data(conn):
    importer.record_game_result(
        conn, 2026, 1, "Cardinals", "Chargers", favorite="away", margin=1.0,
        spread_source="The Odds API, median of 9 books",
    )
    report = import_moneyline_grid(conn, 2026, SAMPLE_GRID)
    week_id = db.get_or_create_week(conn, 2026, 1)
    game = conn.execute(
        "SELECT * FROM lp_game WHERE week_id = ? AND away_team = 'Cardinals' AND home_team = 'Chargers'",
        (week_id,),
    ).fetchone()
    assert game["favorite"] == "away"
    assert game["spread_margin"] == 1.0
    assert report.skipped_market_data_present >= 1


def test_import_moneyline_grid_overwrites_season_spreads_projection(conn):
    from loser_pool.season_spreads import PROJECTION_SOURCE_LABEL

    importer.record_game_result(
        conn, 2026, 1, "Cardinals", "Chargers", favorite="home", margin=5.0,
        spread_source=PROJECTION_SOURCE_LABEL,
    )
    import_moneyline_grid(conn, 2026, SAMPLE_GRID)
    week_id = db.get_or_create_week(conn, 2026, 1)
    game = conn.execute(
        "SELECT * FROM lp_game WHERE week_id = ? AND away_team = 'Cardinals' AND home_team = 'Chargers'",
        (week_id,),
    ).fetchone()
    assert game["spread_source"] == MONEYLINE_SOURCE_LABEL


def test_import_moneyline_grid_refreshes_its_own_earlier_import(conn):
    import_moneyline_grid(conn, 2026, SAMPLE_GRID)
    updated_grid = SAMPLE_GRID.replace("-500", "-300").replace("+380", "+250")
    import_moneyline_grid(conn, 2026, updated_grid)
    week_id = db.get_or_create_week(conn, 2026, 1)
    game = conn.execute(
        "SELECT * FROM lp_game WHERE week_id = ? AND away_team = 'Cardinals' AND home_team = 'Chargers'",
        (week_id,),
    ).fetchone()
    # -300 is a smaller favorite than -500, so the equivalent spread should shrink.
    assert 0 < game["spread_margin"] < 10


def test_import_moneyline_grid_falls_back_without_opposing_line(conn):
    text = "Week,1\nArizona Cardinals,+380  @LAC\n"
    import_moneyline_grid(conn, 2026, text)
    week_id = db.get_or_create_week(conn, 2026, 1)
    game = conn.execute(
        "SELECT * FROM lp_game WHERE week_id = ? AND away_team = 'Cardinals' AND home_team = 'Chargers'",
        (week_id,),
    ).fetchone()
    assert game is not None
    assert game["favorite"] == "home"


def test_import_moneyline_grid_skips_conflicting_orientation(conn):
    text = (
        "Week,1\n"
        "Arizona Cardinals,+380  @LAC\n"
        "Los Angeles Chargers,-500  @ARI\n"  # LAC also claims away -> conflict
    )
    report = import_moneyline_grid(conn, 2026, text)
    week_id = db.get_or_create_week(conn, 2026, 1)
    games = conn.execute(
        "SELECT * FROM lp_game WHERE week_id = ? AND (away_team = 'Cardinals' OR home_team = 'Cardinals')",
        (week_id,),
    ).fetchall()
    assert len(games) == 1
    assert report.skipped_orientation_conflict >= 1
