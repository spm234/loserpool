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


def test_render_dashboard_html_with_ownership():
    pass  # covered via CLI integration test instead — ownership needs sheet CSV, not DB


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
