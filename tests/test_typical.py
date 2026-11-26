from datetime import date, datetime, timedelta

import main
from conftest import add_events

TODAY = date(2026, 11, 25)          # a Wednesday


def add_dinner(day, people=100, arrive="17:05", leave="20:05", hall="portola"):
    """`people` walk in at `arrive` and all walk out at `leave`."""
    arrive_at = datetime.fromisoformat(f"{day}T{arrive}")
    leave_at = datetime.fromisoformat(f"{day}T{leave}")
    add_events(hall, "entrance", [arrive_at] * people)
    add_events(hall, "exit", [leave_at] * people)


def dinner(result):
    return next(m for m in result["meals"] if m["meal"] == "dinner")


def test_slots_cover_the_meal_in_15_minute_steps():
    for weeks_back in (1, 2, 3):
        add_dinner(TODAY - timedelta(weeks=weeks_back))
    slots = dinner(main.typical_day("portola", TODAY))["slots"]
    assert [s["time"] for s in slots][:3] == ["17:00", "17:15", "17:30"]
    assert slots[-1]["time"] == "20:45"
    assert len(slots) == 16


def test_percent_is_the_average_over_past_weeks():
    # 100 people inside from 17:05 to 20:05 every week: 100 / 600 seats = 17%
    for weeks_back in (1, 2, 3):
        add_dinner(TODAY - timedelta(weeks=weeks_back))
    by_time = {s["time"]: s["percent"] for s in dinner(main.typical_day("portola", TODAY))["slots"]}
    assert by_time["17:00"] == 17       # measured at 17:07:30, after they arrived
    assert by_time["19:45"] == 17
    assert by_time["20:00"] == 0        # measured at 20:07:30, after they left


def test_different_weeks_are_averaged():
    add_dinner(TODAY - timedelta(weeks=1), people=60)
    add_dinner(TODAY - timedelta(weeks=2), people=120)
    add_dinner(TODAY - timedelta(weeks=3), people=180)
    meal = dinner(main.typical_day("portola", TODAY))
    assert meal["weeks"] == 3
    assert meal["slots"][4]["percent"] == 20     # (60 + 120 + 180) / 3 = 120 of 600


def test_fewer_than_three_weeks_shows_nothing():
    add_dinner(TODAY - timedelta(weeks=1))
    add_dinner(TODAY - timedelta(weeks=2))
    assert main.typical_day("portola", TODAY)["meals"] == []


def test_quiet_days_are_skipped_not_counted_as_empty():
    for weeks_back in (1, 2, 3):
        add_dinner(TODAY - timedelta(weeks=weeks_back))
    add_dinner(TODAY - timedelta(weeks=4), people=10)    # sensor half off that day
    meal = dinner(main.typical_day("portola", TODAY))
    assert meal["weeks"] == 3
    assert meal["slots"][4]["percent"] == 17


def test_only_the_same_weekday_counts():
    for days_back in (1, 2, 3, 8, 9, 10):    # never a Wednesday
        add_dinner(TODAY - timedelta(days=days_back))
    assert main.typical_day("portola", TODAY)["meals"] == []


def test_looks_back_at_most_eight_weeks():
    for weeks_back in (9, 10, 11):
        add_dinner(TODAY - timedelta(weeks=weeks_back))
    assert main.typical_day("portola", TODAY)["meals"] == []


def test_uses_the_correction_factor_of_that_day():
    # Each past dinner loses 20% of exits (k = 1.25), learned from earlier dinners
    for days_back in range(1, 40):
        day = TODAY - timedelta(days=days_back)
        add_events("portola", "entrance", [datetime.fromisoformat(f"{day}T17:05")] * 100)
        add_events("portola", "exit", [datetime.fromisoformat(f"{day}T18:05")] * 80)
    by_time = {s["time"]: s["percent"] for s in dinner(main.typical_day("portola", TODAY))["slots"]}
    assert by_time["18:00"] == 0     # 100 - 1.25 * 80 = 0, not 20 people


def test_other_halls_dont_mix_in():
    for weeks_back in (1, 2, 3):
        add_dinner(TODAY - timedelta(weeks=weeks_back), hall="dlg")
    assert main.typical_day("portola", TODAY)["meals"] == []
    assert dinner(main.typical_day("dlg", TODAY))["slots"][4]["percent"] == 25   # 100 of 400


def test_worked_out_once_per_day(monkeypatch):
    calls = []
    real = main.count_events
    monkeypatch.setattr(main, "count_events", lambda *a: calls.append(a) or real(*a))
    main.typical_day("portola", TODAY)
    first = len(calls)
    main.typical_day("portola", TODAY)
    assert len(calls) == first                    # cached
    main.typical_day("portola", TODAY + timedelta(days=1))
    assert len(calls) > first                     # a new day is worked out again


def test_endpoint_shape_and_unknown_hall():
    from fastapi.testclient import TestClient
    client = TestClient(main.app)
    r = client.get("/typical", params={"hall": "portola"})
    assert r.status_code == 200
    assert r.json()["meals"] == [] and r.json()["slot_minutes"] == 15
    assert client.get("/typical", params={"hall": "nowhere"}).status_code == 404
