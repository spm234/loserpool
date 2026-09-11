import pytest

from loser_pool import db, importer, picks
from loser_pool.team_page import (
    all_teams_with_pages,
    current_elo_rating,
    team_pickers,
    team_record,
    team_schedule,
)


@pytest.fixture
def conn(tmp_path):
    db_path = tmp_path / "test.db"
    db.init_db(db_path)
    c = db.connect(db_path)
    yield c
    c.close()


def test_team_schedule_basic(conn):
    importer.record_game_result(conn, 2026, 1, "Jaguars", "Browns", favorite="home", margin=10)
    rows = team_schedule(conn, 2026, "Jaguars")
    assert len(rows) == 1
    assert rows[0].opponent == "Browns"
    assert rows[0].is_home is False
    assert rows[0].p_lose > 0.5  # Jaguars are the underdog (Browns favored)


def test_team_schedule_resolves_full_name_input(conn):
    importer.record_game_result(conn, 2026, 1, "Jacksonville Jaguars", "Cleveland Browns", favorite="home", margin=10)
    rows = team_schedule(conn, 2026, "Jaguars")  # nickname lookup should still find it
    assert len(rows) == 1


def test_team_schedule_outcome_win_loss(conn):
    importer.record_game_result(conn, 2026, 1, "Jaguars", "Browns", outcome="away")  # Jaguars (away) won
    importer.record_game_result(conn, 2026, 2, "Bengals", "Jaguars", outcome="away")  # Jaguars (home) lost
    rows = team_schedule(conn, 2026, "Jaguars")
    assert rows[0].outcome == "win"
    assert rows[1].outcome == "loss"


def test_team_schedule_no_outcome_yet_is_none(conn):
    importer.import_schedule(conn, 2026, 1, "Jaguars,Browns\n")
    rows = team_schedule(conn, 2026, "Jaguars")
    assert rows[0].outcome is None


def test_team_record_counts_correctly(conn):
    importer.record_game_result(conn, 2026, 1, "Jaguars", "Browns", outcome="away")
    importer.record_game_result(conn, 2026, 2, "Bengals", "Jaguars", outcome="away")
    importer.record_game_result(conn, 2026, 3, "Jaguars", "Titans", outcome="tie")
    rows = team_schedule(conn, 2026, "Jaguars")
    assert team_record(rows) == "1-1-1"


def test_team_record_no_ties_omits_third_number(conn):
    importer.record_game_result(conn, 2026, 1, "Jaguars", "Browns", outcome="away")
    rows = team_schedule(conn, 2026, "Jaguars")
    assert team_record(rows) == "1-0"


def test_team_pickers_lists_entries_and_results(conn):
    importer.import_schedule(conn, 2026, 1, "Jaguars,Browns\n")
    picks.record_pick(conn, 2026, 1, "A", "Jaguars")
    picks.record_pick(conn, 2026, 1, "B", "Jaguars")
    rows = team_pickers(conn, 2026, "Jaguars")
    assert {r.entry_name for r in rows} == {"A", "B"}
    assert all(r.result == "pending" for r in rows)


def test_team_pickers_empty_when_nobody_has_picked_them(conn):
    importer.import_schedule(conn, 2026, 1, "Jaguars,Browns\n")
    assert team_pickers(conn, 2026, "Jaguars") == []


def test_current_elo_rating_defaults_to_initial(conn):
    from loser_pool.config import LoserPoolConfig
    cfg = LoserPoolConfig.load(conn)
    assert current_elo_rating(conn, 2026, "Jaguars", 1) == cfg.elo_initial_rating


def test_all_teams_with_pages_includes_standard_32_plus_extras(conn):
    importer.import_schedule(conn, 2026, 1, "TeamX,TeamY\n")
    teams = all_teams_with_pages(conn, 2026)
    assert len(teams) >= 32
    assert "TeamX" in teams
    assert "Jaguars" in teams
