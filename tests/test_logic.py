from datetime import date, datetime, timedelta

import main
from conftest import add_events

DAY = date(2026, 10, 28)


def at(hhmm, day=DAY):
    return datetime.fromisoformat(f"{day}T{hhmm}")


def add_past_meal(days_back, entries, exits, meal="dinner", hall="portola"):
    """Put `entries` and `exits` events inside one past meal."""
    start, _ = main.meal_window(DAY - timedelta(days=days_back), meal)
    first_exit = start + timedelta(hours=1)
    add_events(hall, "entrance", [start + timedelta(seconds=i) for i in range(entries)])
    add_events(hall, "exit", [first_exit + timedelta(seconds=i) for i in range(exits)])


# ---------------- get_hall ----------------

def test_get_hall_known_and_unknown():
    assert main.get_hall("portola") == ("Portola", 600)
    assert main.get_hall("nope") is None


# ---------------- meal_window / current_meal ----------------

def test_meal_window_returns_start_and_end():
    assert main.meal_window(DAY, "lunch") == (at("11:00"), at("15:00"))


def test_meal_window_unknown_meal():
    assert main.meal_window(DAY, "demo") is None


def test_current_meal_inside_and_at_edges():
    assert main.current_meal(at("07:00")) == ("breakfast", at("07:00"))
    assert main.current_meal(at("18:30")) == ("dinner", at("17:00"))
    # End time is exclusive
    assert main.current_meal(at("10:30")) is None
    assert main.current_meal(at("21:00")) is None


def test_current_meal_between_meals():
    assert main.current_meal(at("16:00")) is None
    assert main.current_meal(at("03:00")) is None


def test_current_meal_always_open(monkeypatch):
    monkeypatch.setattr(main, "ALWAYS_OPEN", True)
    assert main.current_meal(at("03:15")) == ("demo", at("00:00"))


# ---------------- count_events ----------------

def test_count_events_start_inclusive_end_exclusive():
    add_events("portola", "entrance", [at("17:00"), at("17:30"), at("18:00")])
    add_events("portola", "exit", [at("17:30")])
    add_events("dlg", "entrance", [at("17:30")])
    assert main.count_events("portola", "entrance", at("17:00"), at("18:00")) == 2
    assert main.count_events("portola", "exit", at("17:00"), at("18:00")) == 1
    assert main.count_events("dlg", "entrance", at("17:00"), at("18:00")) == 1


# ---------------- correction_factor ----------------

def test_correction_factor_no_history():
    assert main.correction_factor("portola", "dinner", at("18:00")) == (1.0, 0)


def test_correction_factor_pools_past_meals():
    add_past_meal(1, entries=100, exits=80)
    add_past_meal(2, entries=60, exits=50)
    k, used = main.correction_factor("portola", "dinner", at("18:00"))
    assert used == 2
    assert k == (100 + 60) / (80 + 50)


def test_correction_factor_skips_bad_meals():
    add_past_meal(1, entries=49, exits=40)     # too few entries
    add_past_meal(2, entries=100, exits=0)     # exit sensor off
    add_past_meal(3, entries=100, exits=50)    # k = 2.0: hardware problem
    add_past_meal(4, entries=100, exits=200)   # k = 0.5: hardware problem
    assert main.correction_factor("portola", "dinner", at("18:00")) == (1.0, 0)


def test_correction_factor_counts_exits_up_to_an_hour_after_closing():
    start, end = main.meal_window(DAY - timedelta(days=1), "dinner")
    add_events("portola", "entrance", [start] * 100)
    add_events("portola", "exit", [end + timedelta(minutes=30)] * 90)
    add_events("portola", "exit", [end + timedelta(hours=1)] * 10)   # too late
    assert main.correction_factor("portola", "dinner", at("18:00")) == (100 / 90, 1)


def test_correction_factor_only_same_meal_type():
    add_past_meal(1, entries=100, exits=80, meal="lunch")
    assert main.correction_factor("portola", "dinner", at("18:00")) == (1.0, 0)


def test_correction_factor_stops_at_k_meals(monkeypatch):
    monkeypatch.setattr(main, "K_MEALS", 2)
    add_past_meal(1, entries=100, exits=100)
    add_past_meal(2, entries=100, exits=100)
    add_past_meal(3, entries=100, exits=70)    # would change k if it were used
    assert main.correction_factor("portola", "dinner", at("18:00")) == (1.0, 2)


def test_correction_factor_looks_back_at_most_60_days():
    add_past_meal(61, entries=100, exits=80)
    assert main.correction_factor("portola", "dinner", at("18:00")) == (1.0, 0)


def test_correction_factor_demo_meal_has_no_history():
    add_past_meal(1, entries=100, exits=80)
    assert main.correction_factor("portola", "demo", at("18:00")) == (1.0, 0)


# ---------------- estimate_occupancy ----------------

def test_estimate_occupancy_closed():
    assert main.estimate_occupancy("portola", at("16:00")) == {
        "hall": "portola", "name": "Portola", "capacity": 600, "status": "closed",
    }


def test_estimate_occupancy_open_uses_k():
    add_past_meal(1, entries=100, exits=80)    # k = 1.25
    add_events("portola", "entrance", [at("17:10")] * 50)
    add_events("portola", "exit", [at("17:40")] * 20)
    result = main.estimate_occupancy("portola", at("18:00"))
    assert result == {
        "hall": "portola", "name": "Portola", "capacity": 600,
        "status": "open", "meal": "dinner",
        "entries": 50, "exits": 20, "k": 1.25, "k_meals_used": 1,
        "people": 25, "percent": 4,
    }


def test_estimate_occupancy_ignores_events_before_meal_and_after_now():
    add_events("portola", "entrance", [at("16:59"), at("17:05"), at("18:00")])
    result = main.estimate_occupancy("portola", at("18:00"))
    assert result["entries"] == 1


def test_estimate_occupancy_never_below_zero():
    add_events("portola", "exit", [at("17:10")] * 5)
    result = main.estimate_occupancy("portola", at("18:00"))
    assert result["people"] == 0
    assert result["percent"] == 0


def test_estimate_occupancy_never_above_capacity():
    add_events("dlg", "entrance", [at("17:10")] * 450)
    result = main.estimate_occupancy("dlg", at("18:00"))
    assert result["people"] == 400
    assert result["percent"] == 100
