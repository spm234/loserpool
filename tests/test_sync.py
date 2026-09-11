from datetime import datetime, timezone

import pytest

from loser_pool import db, sync
from loser_pool import live_data
from loser_pool.config import LoserPoolConfig


@pytest.fixture
def conn(tmp_path):
    db_path = tmp_path / "test.db"
    db.init_db(db_path)
    c = db.connect(db_path)
    yield c
    c.close()


def _set_week1(conn, iso_date):
    cfg = LoserPoolConfig.load(conn)
    cfg.season_week1_date = iso_date
    cfg.save(conn)


def test_sync_week_discovers_games_matching_the_target_week(conn, monkeypatch):
    _set_week1(conn, "2026-09-08")

    def fake_list_board_events(api_key=None):
        return [
            live_data.BoardEvent(
                "Jaguars", "Browns", datetime(2026, 9, 10, tzinfo=timezone.utc), "home", 3.0, "test",
            ),
            live_data.BoardEvent(
                # week 2 game (Sept 17 falls in the Sept 15-21 window) - should be excluded
                "Bengals", "Ravens", datetime(2026, 9, 17, tzinfo=timezone.utc), "away", 6.0, "test",
            ),
        ]

    monkeypatch.setattr(sync.live_data, "list_board_events", fake_list_board_events)
    monkeypatch.setattr(
        sync.live_data, "fetch_and_save_result",
        lambda *a, **k: (_ for _ in ()).throw(live_data.LiveDataError("not finished")),
    )

    report = sync.sync_week(conn, 2026, 1, api_key="fake")
    assert report.games_discovered == 1
    assert report.spreads_recorded == 1

    week_id = db.get_or_create_week(conn, 2026, 1)
    games = conn.execute("SELECT away_team, home_team FROM lp_game WHERE week_id = ?", (week_id,)).fetchall()
    assert [(g["away_team"], g["home_team"]) for g in games] == [("Jaguars", "Browns")]


def test_sync_week_records_results_and_settles(conn, monkeypatch):
    _set_week1(conn, "2026-09-08")

    def fake_list_board_events(api_key=None):
        return [
            live_data.BoardEvent(
                "Jaguars", "Browns", datetime(2026, 9, 10, tzinfo=timezone.utc), "home", 3.0, "test",
            ),
        ]

    def fake_fetch_and_save_result(conn_, season_year, week_number, away_team, home_team, *, api_key=None):
        from loser_pool import importer
        importer.record_game_result(
            conn_, season_year, week_number, away_team, home_team, outcome="home",
            home_score=24, away_score=10,
        )
        return object()

    from loser_pool.picks import record_pick

    monkeypatch.setattr(sync.live_data, "list_board_events", fake_list_board_events)
    monkeypatch.setattr(
        sync.live_data, "fetch_and_save_result",
        lambda *a, **k: (_ for _ in ()).throw(live_data.LiveDataError("not finished")),
    )

    # Discover the schedule first (game not finished yet) so a pick can be
    # recorded against it before any result exists.
    sync.sync_week(conn, 2026, 1, api_key="fake")
    record_pick(conn, 2026, 1, "SPM", "Jaguars", is_mine=True)

    # Now the game finishes — re-run sync, which should fetch+record the
    # result and settle the pending pick against it.
    monkeypatch.setattr(sync.live_data, "fetch_and_save_result", fake_fetch_and_save_result)
    report = sync.sync_week(conn, 2026, 1, api_key="fake")
    assert report.results_recorded == 1
    assert len(report.settled) == 1
    assert report.settled[0].outcome == "survived"  # Jaguars (away) lost -> good pick

    entry = db.get_entry_by_name(conn, "SPM")
    assert entry["lives_remaining"] == 2


def test_sync_week_handles_board_fetch_failure_gracefully(conn, monkeypatch):
    def fake_list_board_events(api_key=None):
        raise live_data.LiveDataError("no api key")

    monkeypatch.setattr(sync.live_data, "list_board_events", fake_list_board_events)
    report = sync.sync_week(conn, 2026, 1, api_key=None)
    assert report.games_discovered == 0
    assert len(report.fetch_errors) == 1


def test_sync_week_without_week1_date_imports_everything_on_the_board(conn, monkeypatch):
    def fake_list_board_events(api_key=None):
        return [
            live_data.BoardEvent(
                "Jaguars", "Browns", datetime(2026, 9, 10, tzinfo=timezone.utc), None, 0.0, "test",
            ),
        ]

    monkeypatch.setattr(sync.live_data, "list_board_events", fake_list_board_events)
    monkeypatch.setattr(
        sync.live_data, "fetch_and_save_result",
        lambda *a, **k: (_ for _ in ()).throw(live_data.LiveDataError("not finished")),
    )
    report = sync.sync_week(conn, 2026, 5, api_key="fake")
    assert report.games_discovered == 1
    assert report.spreads_recorded == 0  # favorite=None -> no spread posted yet
