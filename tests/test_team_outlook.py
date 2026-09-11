import pytest

from loser_pool import db, importer, picks
from loser_pool.team_outlook import (
    best_week_per_team,
    known_weeks,
    season_to_date_team_usage,
    team_week_matrix,
    weekly_biggest_underdogs,
)


@pytest.fixture
def conn(tmp_path):
    db_path = tmp_path / "test.db"
    db.init_db(db_path)
    c = db.connect(db_path)
    yield c
    c.close()


def test_season_to_date_team_usage_includes_all_32_teams_at_zero(conn):
    usage = season_to_date_team_usage(conn, 2026)
    assert len(usage) >= 32
    assert all(u.times_picked == 0 for u in usage)


def test_season_to_date_team_usage_counts_distinct_entries(conn):
    importer.import_schedule(conn, 2026, 1, "Jaguars,Browns\n")
    picks.record_pick(conn, 2026, 1, "A", "Jaguars")
    picks.record_pick(conn, 2026, 1, "B", "Jaguars")
    usage = season_to_date_team_usage(conn, 2026)
    by_team = {u.team: u.times_picked for u in usage}
    assert by_team["Jaguars"] == 2
    assert by_team["Browns"] == 0


def test_season_to_date_team_usage_respects_playoff_reset(conn):
    importer.import_schedule(conn, 2026, 1, "Jaguars,Browns\n")
    picks.record_pick(conn, 2026, 1, "A", "Jaguars")
    picks.trigger_playoff_reset(conn, reset_after_week_number=17)
    usage = season_to_date_team_usage(conn, 2026)
    by_team = {u.team: u.times_picked for u in usage}
    assert by_team["Jaguars"] == 0  # pre-reset pick no longer counts


def test_known_weeks_only_lists_weeks_with_games(conn):
    importer.import_schedule(conn, 2026, 1, "Jaguars,Browns\n")
    importer.import_schedule(conn, 2026, 3, "Bengals,Ravens\n")
    assert known_weeks(conn, 2026) == [1, 3]


def test_known_weeks_excludes_playoff_weeks_above_18(conn):
    importer.import_schedule(conn, 2026, 1, "Jaguars,Browns\n")
    importer.import_schedule(conn, 2026, 20, "Jaguars,Ravens\n", is_playoffs=True)
    assert known_weeks(conn, 2026) == [1]


def test_team_week_matrix_has_both_sides_of_each_game(conn):
    importer.record_game_result(conn, 2026, 1, "Jaguars", "Browns", favorite="home", margin=10)
    matrix = team_week_matrix(conn, 2026, [1])
    assert 1 in matrix["Jaguars"]
    assert 1 in matrix["Browns"]
    # Browns favored by 10 -> Jaguars (away) is the underdog, higher p_lose... wait
    # Jaguars is the team likely to LOSE (favorite=home favored), so Jaguars p_lose is high.
    assert matrix["Jaguars"][1].p_lose > matrix["Browns"][1].p_lose


def test_weekly_biggest_underdogs_sorted_descending(conn):
    importer.record_game_result(conn, 2026, 1, "Jaguars", "Browns", favorite="home", margin=20)
    importer.record_game_result(conn, 2026, 1, "Bengals", "Ravens", favorite=None, margin=0)
    top = weekly_biggest_underdogs(conn, 2026, [1], top_n=2)
    assert top[1][0].team == "Jaguars"  # biggest mismatch first


def test_best_week_per_team_picks_highest_p_lose(conn):
    importer.record_game_result(conn, 2026, 1, "Jaguars", "Browns", favorite="home", margin=3)
    importer.record_game_result(conn, 2026, 2, "Jaguars", "Ravens", favorite="home", margin=20)
    matrix = team_week_matrix(conn, 2026, [1, 2])
    best = best_week_per_team(matrix)
    jaguars_best = next(o for o in best if o.team == "Jaguars")
    assert jaguars_best.week_number == 2
