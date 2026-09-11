import pytest

from loser_pool import db, importer, picks
from loser_pool.export_html import render_dashboard_html, render_team_page_html, render_teams_index_html


@pytest.fixture
def conn(tmp_path):
    db_path = tmp_path / "test.db"
    db.init_db(db_path)
    c = db.connect(db_path)
    yield c
    c.close()


def test_render_team_page_html_basic(conn):
    importer.record_game_result(conn, 2026, 1, "Jaguars", "Browns", favorite="home", margin=10)
    html = render_team_page_html(conn, 2026, "Jaguars")
    assert "<html>" in html
    assert "Jaguars" in html
    assert "Browns" in html
    assert "Back to dashboard" in html
    assert "../index.html" in html


def test_render_team_page_html_shows_color_coded_loss_probability(conn):
    importer.record_game_result(conn, 2026, 1, "Jaguars", "Browns", favorite="home", margin=20)  # Jaguars big dog
    html = render_team_page_html(conn, 2026, "Jaguars")
    assert "plose-good" in html  # Jaguars are heavy underdogs here


def test_render_team_page_html_shows_win_loss_outcome(conn):
    importer.record_game_result(conn, 2026, 1, "Jaguars", "Browns", outcome="away")  # Jaguars won
    html = render_team_page_html(conn, 2026, "Jaguars")
    assert "outcome-win" in html
    assert "1-0" in html  # record


def test_render_team_page_html_shows_pickers(conn):
    importer.import_schedule(conn, 2026, 1, "Jaguars,Browns\n")
    picks.record_pick(conn, 2026, 1, "SPM", "Jaguars", is_mine=True)
    html = render_team_page_html(conn, 2026, "Jaguars")
    assert "SPM" in html
    assert "picked by 1 entry" in html


def test_render_team_page_html_no_pickers_message(conn):
    importer.import_schedule(conn, 2026, 1, "Jaguars,Browns\n")
    html = render_team_page_html(conn, 2026, "Jaguars")
    assert "Nobody" in html


def test_render_teams_index_html_links_all_known_teams(conn):
    html = render_teams_index_html(conn, 2026)
    assert "Jaguars" in html
    assert "jax.html" in html
    assert "Back to dashboard" in html


def test_render_dashboard_html_links_team_names_to_team_pages(conn):
    importer.import_schedule(conn, 2026, 1, "Jaguars,Browns\n")
    picks.record_pick(conn, 2026, 1, "SPM", "Jaguars", is_mine=True)
    html = render_dashboard_html(conn, 2026, 1)
    assert "teams/jax.html" in html
    assert "All Teams" in html
    assert "teams/index.html" in html


def test_render_dashboard_html_unknown_team_not_linked(conn):
    importer.import_schedule(conn, 2026, 1, "TeamA,TeamB\n")
    picks.record_pick(conn, 2026, 1, "SPM", "TeamA", is_mine=True)
    html = render_dashboard_html(conn, 2026, 1)
    assert "TeamA" in html
    assert "teams/TeamA" not in html
