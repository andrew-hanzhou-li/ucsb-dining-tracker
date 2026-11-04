"""
Fills dining.db with fake meals for the past DAYS days, then checks how well
the server's formula tracks the TRUE number of people inside.

For testing only. Never run this against a database with real sensor data:
it deletes events in the date range it simulates.
"""
import random
import sqlite3
from datetime import datetime, timedelta

import main   # reuse the server's own formula, so we test the real thing

# ------------------------------------------------------------
# Settings (made-up numbers; tune them once you have real data)
# ------------------------------------------------------------
DAYS = 14                  # how many past days to fill
# Share of people who walk out beside someone and aren't counted by the exit sensor
HIDDEN_EXIT_RATE = 0.12

# People per meal at Portola
VISITORS = {"breakfast": 250, "lunch": 700, "dinner": 900}
# Minutes after opening when the rush peaks
PEAK_MINUTE = {"breakfast": 60, "lunch": 90, "dinner": 75}
# The other halls get fewer visitors than Portola
HALL_SIZE = {"portola": 1.0, "carrillo": 0.7, "dlg": 0.7}

random.seed(42)            # same fake data every run, so your output matches the guide.
                           # Delete this line to get different data each time.

CHECK_HALL = "portola"     # which hall and meal to grade at the end
CHECK_MEAL = "dinner"


def simulate_meal(hall, day, meal_name):
    """Make up one meal. Returns (sensor_events, truth)."""
    start, end = main.meal_window(day, meal_name)
    meal_minutes = (end - start).total_seconds() / 60
    visitors = int(VISITORS[meal_name] * HALL_SIZE[hall] * random.uniform(0.85, 1.15))

    sensor_events = []   # what the sensors would record
    truth = []           # (arrive, leave) for every real person

    for i in range(visitors):
        arrive_minute = random.triangular(0, meal_minutes - 10, PEAK_MINUTE[meal_name])
        stay_minutes = min(max(random.gauss(25, 8), 8), 60)
        arrive = start + timedelta(minutes=arrive_minute)
        leave = arrive + timedelta(minutes=stay_minutes)
        truth.append((arrive, leave))

        # The entrance is single file through the ID check, so it's always counted
        sensor_events.append((hall, "entrance", arrive.isoformat()))
        # The exit misses some people who leave side by side with someone
        if random.random() > HIDDEN_EXIT_RATE:
            sensor_events.append((hall, "exit", leave.isoformat()))

    return sensor_events, truth


def true_inside(truth, t):
    """How many people were really inside at time t."""
    count = 0
    for arrive, leave in truth:
        if arrive <= t < leave:
            count += 1
    return count


# ------------------------------------------------------------
# 1. Fill the database
# ------------------------------------------------------------
if main.ALWAYS_OPEN:
    print("Set ALWAYS_OPEN = False in main.py before running the simulator.")
    raise SystemExit

db = sqlite3.connect("dining.db")
today = datetime.now().date()
first_day = today - timedelta(days=DAYS)

# Clear old simulated data in this range so re-running starts fresh
db.execute("DELETE FROM events WHERE time >= ? AND time < ?",
           (first_day.isoformat(), today.isoformat()))

total_events = 0
check_truth = None
for days_back in range(DAYS, 0, -1):
    day = today - timedelta(days=days_back)
    for hall in HALL_SIZE:
        for meal_name, start, end in main.MEALS:
            events, truth = simulate_meal(hall, day, meal_name)
            db.executemany("INSERT INTO events VALUES (?, ?, ?)", events)
            total_events += len(events)
            # Remember yesterday's Portola dinner so we can grade it below
            if days_back == 1 and hall == CHECK_HALL and meal_name == CHECK_MEAL:
                check_truth = truth
db.commit()
print(f"Added {total_events:,} fake events over {DAYS} days.")
print(f"True k should be about {1 / (1 - HIDDEN_EXIT_RATE):.3f}\n")

# ------------------------------------------------------------
# 2. Grade the formula on yesterday's dinner
# ------------------------------------------------------------
yesterday = today - timedelta(days=1)
start, end = main.meal_window(yesterday, CHECK_MEAL)

times = []
truth_values = []
naive_values = []
corrected_values = []

print("time    truth   naive (k=1)   corrected")
t = start + timedelta(minutes=10)
while t < end:
    result = main.estimate_occupancy(CHECK_HALL, t)
    naive = max(0, result["entries"] - result["exits"])
    real = true_inside(check_truth, t)

    times.append(t)
    truth_values.append(real)
    naive_values.append(naive)
    corrected_values.append(result["people"])
    if t.minute % 30 == 0:
        print(f"{t:%H:%M}   {real:5}   {naive:11}   {result['people']:9}")
    t += timedelta(minutes=5)

print(f"\nk used: {result['k']} (from {result['k_meals_used']} past dinners)")


def average_error(estimates):
    total = 0
    for est, real in zip(estimates, truth_values):
        total += abs(est - real)
    return total / len(truth_values)


print(f"Average error without k: {average_error(naive_values):.0f} people")
print(f"Average error with k:    {average_error(corrected_values):.0f} people")

# ------------------------------------------------------------
# 3. Chart it (optional: needs `python -m pip install matplotlib`)
# ------------------------------------------------------------
try:
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
except ImportError:
    print("\n(Install matplotlib to also get a chart.)")
    raise SystemExit

plt.figure(figsize=(9, 4.5))
plt.plot(times, truth_values, label="True people inside", linewidth=2.5, color="black")
plt.plot(times, naive_values, label="Estimate without k",
         linestyle="--", color="#d98a14")
plt.plot(times, corrected_values, label="Estimate with k", color="#0f7c8c")
plt.title(f"{CHECK_HALL.title()} {CHECK_MEAL}, {yesterday} (simulated)")
plt.ylabel("People inside")
plt.legend()
plt.gca().xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
plt.tight_layout()
plt.savefig("simulation_check.png", dpi=150)
print("\nSaved chart to simulation_check.png")
