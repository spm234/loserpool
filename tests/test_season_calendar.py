from datetime import date, timedelta

from loser_pool.season_calendar import week_number_for_date


def test_week1_start_date_is_week_1():
    assert week_number_for_date(date(2026, 9, 8), date(2026, 9, 8)) == 1


def test_date_before_week1_clamps_to_week_1():
    assert week_number_for_date(date(2026, 9, 8), date(2026, 8, 1)) == 1


def test_last_day_of_week1_window_is_still_week_1():
    assert week_number_for_date(date(2026, 9, 8), date(2026, 9, 14)) == 1


def test_first_day_of_week2_window_is_week_2():
    assert week_number_for_date(date(2026, 9, 8), date(2026, 9, 15)) == 2


def test_week_18_boundary():
    # 17 full weeks after week1_start's window ends = week 18 starts
    week1_start = date(2026, 9, 8)
    assert week_number_for_date(week1_start, week1_start + timedelta(days=17 * 7)) == 18


def test_dates_past_regular_season_clamp_to_max_week():
    assert week_number_for_date(date(2026, 9, 8), date(2027, 3, 1)) == 18


def test_custom_max_week():
    assert week_number_for_date(date(2026, 9, 8), date(2027, 1, 1), max_week=5) == 5
