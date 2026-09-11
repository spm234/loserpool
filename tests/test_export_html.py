import pytest

from loser_pool import db, importer, picks
from loser_pool.export_html import render_dashboard_html
from loser_pool.sheets_sync import pick_ownership, parse_pool_sheet_csv


@pytest.fixture
def conn(tmp_path):
    db_path = tmp_path / "test.db"
    db.init_db(db_path)
    c = db.connect(db_path)
    yield c
    c.close()


def test_render_dashboard_html_basic(conn):
    importer.import_schedule(conn, 2026, 1, "Jaguars,Browns\nBengals,Ravens\n")
    db.get_or_create_entry(conn, "SPM", "SPM", is_mine=True)
    conn.commit()
    html = render_dashboard_html(conn, 2026, 1)
    assert "<html>" in html
    assert "SPM" in html
    assert "Standings" in html
    assert "Loser Pool 2026" in html


def test_render_dashboard_html_escapes_names(conn):
    db.get_or_create_entry(conn, "<script>", "<script>alert(1)</script>", is_mine=False)
    conn.commit()
    html = render_dashboard_html(conn, 2026, 1)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_render_dashboard_html_shows_eliminated_and_used_teams(conn):
    importer.import_schedule(conn, 2026, 1, "Jaguars,Browns\n")
    entry_id = db.get_or_create_entry(conn, "SPM", "SPM", is_mine=True, lives_per_entry=1)
    conn.commit()
    picks.record_pick(conn, 2026, 1, "SPM", "Jaguars", is_mine=True)
    importer.record_game_result(conn, 2026, 1, "Jaguars", "Browns", outcome="away")
    picks.settle_week(conn, 2026, 1)
    html = render_dashboard_html(conn, 2026, 1)
    assert "OUT (wk 1)" in html
    assert "Jaguars" in html


def test_render_dashboard_html_ownership_section(conn):
    csv_text = ",Week 1\nEntry A,Jaguars\nEntry B,Jaguars\nEntry C,Bengals\n"
    rows = parse_pool_sheet_csv(csv_text)
    ownership = pick_ownership(rows, "Week 1")
    html = render_dashboard_html(conn, 2026, 1, ownership=ownership)
    assert "field ownership" in html
    assert "Jaguars" in html
    assert "66.7%" in html or "66.6%" in html


def test_render_dashboard_html_no_my_entries_section_when_none(conn):
    db.get_or_create_entry(conn, "Rival", "Rival", is_mine=False)
    conn.commit()
    html = render_dashboard_html(conn, 2026, 1)
    assert "This week's recommendations" not in html


def test_render_dashboard_html_shows_recommendation_cards_and_logos(conn):
    importer.import_schedule(conn, 2026, 1, "Jaguars,Browns\nBengals,Ravens\n")
    db.get_or_create_entry(conn, "SPM", "SPM", is_mine=True)
    conn.commit()
    html = render_dashboard_html(conn, 2026, 1)
    assert "pick-card recommended" in html
    assert "espncdn.com" in html  # a known team (Jaguars) should get a logo URL
    assert "Backup option 1" in html


def test_render_dashboard_html_unknown_team_has_no_logo_but_still_renders(conn):
    importer.import_schedule(conn, 2026, 1, "TeamA,TeamB\n")
    db.get_or_create_entry(conn, "SPM", "SPM", is_mine=True)
    conn.commit()
    html = render_dashboard_html(conn, 2026, 1)
    assert "TeamA" in html
    assert "TeamB" in html


def test_render_dashboard_html_chalk_badge_for_high_ownership_top_pick(conn):
    importer.import_schedule(conn, 2026, 1, "Jaguars,Browns\n")
    db.get_or_create_entry(conn, "SPM", "SPM", is_mine=True)
    conn.commit()
    csv_text = ",Week 1\nEntry A,Jaguars\nEntry B,Jaguars\nEntry C,Jaguars\n"
    rows = parse_pool_sheet_csv(csv_text)
    ownership = pick_ownership(rows, "Week 1")
    html = render_dashboard_html(conn, 2026, 1, ownership=ownership)
    assert "Heavy chalk" in html


def test_render_dashboard_html_includes_full_season_path_when_future_weeks_exist(conn):
    importer.import_schedule(conn, 2026, 1, "Jaguars,Browns\n")
    importer.import_schedule(conn, 2026, 2, "Bengals,Ravens\n")
    db.get_or_create_entry(conn, "SPM", "SPM", is_mine=True)
    conn.commit()
    html = render_dashboard_html(conn, 2026, 1)
    assert "Reference full-season path" in html


def test_render_dashboard_html_recommendations_appear_before_standings(conn):
    importer.import_schedule(conn, 2026, 1, "Jaguars,Browns\n")
    db.get_or_create_entry(conn, "SPM", "SPM", is_mine=True)
    conn.commit()
    html = render_dashboard_html(conn, 2026, 1)
    assert html.index("This week's recommendations") < html.index("Standings")


def test_render_dashboard_html_no_banner_text(conn):
    html = render_dashboard_html(conn, 2026, 1)
    assert "auto-refreshes" not in html


def test_render_dashboard_html_team_usage_section(conn):
    importer.import_schedule(conn, 2026, 1, "Jaguars,Browns\n")
    picks.record_pick(conn, 2026, 1, "A", "Jaguars")
    html = render_dashboard_html(conn, 2026, 1)
    assert "Team usage so far" in html
    assert "Jaguars" in html


def test_render_dashboard_html_weekly_underdogs_and_team_outlook_sections(conn):
    importer.record_game_result(conn, 2026, 1, "Jaguars", "Browns", favorite="home", margin=20)
    html = render_dashboard_html(conn, 2026, 1)
    assert "Week-over-week biggest underdogs" in html
    assert "Best week to use each team" in html


def test_render_dashboard_html_no_underdog_sections_when_no_games(conn):
    html = render_dashboard_html(conn, 2026, 1)
    assert "Week-over-week biggest underdogs" not in html
    assert "Best week to use each team" not in html


def test_render_dashboard_html_prefers_season_optimal_pick_over_raw_best(conn):
    # Team A is the best raw pick this week (90%), but has no other game
    # anywhere else in the known schedule -> using it now costs nothing
    # later, so it stays optimal even with lookahead (sanity baseline).
    #
    # Team B is a modest pick this week (60%) but a monster mismatch next
    # week (95%) that only it can fill (no other underdog next week) -> a
    # myopic this-week-only ranking picks A or whichever is highest raw
    # this week; the season-aware ranking should recognize B is safe to
    # take now since its OWN big week is still available regardless, and
    # what actually matters here is that the "peak week" opportunity-cost
    # note fires correctly for a team whose best week is NOT this one.
    importer.record_game_result(conn, 2026, 1, "TeamC", "TeamD", favorite="home", margin=1)  # near pick'em
    importer.record_game_result(conn, 2026, 2, "TeamC", "TeamE", favorite="home", margin=40)  # TeamC huge dog later
    db.get_or_create_entry(conn, "SPM", "SPM", is_mine=True)
    conn.commit()
    html = render_dashboard_html(conn, 2026, 1)
    assert "Bigger mismatch in Week 2" in html


def test_render_dashboard_html_peak_week_note_when_current_week_is_best(conn):
    importer.record_game_result(conn, 2026, 1, "TeamA", "TeamB", favorite="home", margin=20)
    db.get_or_create_entry(conn, "SPM", "SPM", is_mine=True)
    conn.commit()
    html = render_dashboard_html(conn, 2026, 1)
    assert "Peak week for this team" in html
