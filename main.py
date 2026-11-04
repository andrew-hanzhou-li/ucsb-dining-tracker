from fastapi import FastAPI, HTTPException, Header
from fastapi.responses import FileResponse
from typing import Literal
from datetime import datetime, timedelta
import os
import sqlite3

app = FastAPI()

# ------------------------------------------------------------
# Settings
# ------------------------------------------------------------

# Every device must send this key. On the VPS it comes from /etc/dining.env;
# on your laptop it falls back to the test key below.
API_KEY = os.environ.get("DINING_API_KEY", "change-me-to-something-long")

# Meal hours. PLACEHOLDERS: replace with the real hours from the dining website.
MEALS = [
    ("breakfast", "07:00", "10:30"),
    ("lunch", "11:00", "15:00"),
    ("dinner", "17:00", "21:00"),
]

# For testing the webpage at any time of day: True treats the whole day as one meal.
ALWAYS_OPEN = False

# How many past meals to use when computing the correction factor k
K_MEALS = 10

# ------------------------------------------------------------
# Database setup
# ------------------------------------------------------------

db = sqlite3.connect("dining.db", check_same_thread=False)
db.execute("CREATE TABLE IF NOT EXISTS events (hall TEXT, lane TEXT, time TEXT)")
db.execute("""CREATE TABLE IF NOT EXISTS halls
              (name TEXT PRIMARY KEY, display_name TEXT, capacity INTEGER)""")

# Capacities: Portola's 600 indoor seats is from the Daily Nexus.
# The other two are PLACEHOLDERS until you get real numbers from Housing.
db.execute("INSERT OR IGNORE INTO halls VALUES ('portola', 'Portola', 600)")
db.execute("INSERT OR IGNORE INTO halls VALUES ('carrillo', 'Carrillo', 400)")
db.execute("INSERT OR IGNORE INTO halls VALUES ('dlg', 'De La Guerra', 400)")
db.commit()


# ------------------------------------------------------------
# Helper functions
# ------------------------------------------------------------

def get_hall(name):
    """Return (display_name, capacity) for a hall, or None if it doesn't exist."""
    return db.execute(
        "SELECT display_name, capacity FROM halls WHERE name = ?", (name,)
    ).fetchone()


def meal_window(day, meal_name):
    """Return (start, end) datetimes for one meal on one day."""
    for name, start, end in MEALS:
        if name == meal_name:
            start_dt = datetime.fromisoformat(f"{day}T{start}")
            end_dt = datetime.fromisoformat(f"{day}T{end}")
            return start_dt, end_dt
    return None


def current_meal(now):
    """Return (meal_name, start_time) if a meal is happening at `now`, else None."""
    if ALWAYS_OPEN:
        midnight = datetime(now.year, now.month, now.day)
        return "demo", midnight
    for name, start, end in MEALS:
        start_dt, end_dt = meal_window(now.date(), name)
        if start_dt <= now < end_dt:
            return name, start_dt
    return None


def count_events(hall, lane, start, end):
    """Count events for one hall and lane with start <= time < end."""
    row = db.execute(
        """SELECT COUNT(*) FROM events
           WHERE hall = ? AND lane = ? AND time >= ? AND time < ?""",
        (hall, lane, start.isoformat(), end.isoformat()),
    ).fetchone()
    return row[0]


def correction_factor(hall, meal_name, now):
    """
    k = total entries / total sensed exits, pooled over the last K_MEALS
    completed meals of the same type (dinners with dinners, etc.).
    Returns (k, number_of_meals_used).
    """
    total_in = 0
    total_out = 0
    meals_used = 0

    for days_back in range(1, 61):
        day = now.date() - timedelta(days=days_back)
        window = meal_window(day, meal_name)
        if window is None:          # e.g. the "demo" meal has no history
            break
        start, end = window

        entries = count_events(hall, "entrance", start, end)
        # People are still walking out after closing, so give exits an extra hour
        exits = count_events(hall, "exit", start, end + timedelta(hours=1))

        # Skip meals with too little data (closed that day, sensor off...)
        if entries < 50 or exits == 0:
            continue
        # Skip meals where k is clearly a hardware problem, not behavior
        k = entries / exits
        if k < 0.8 or k > 1.6:
            continue

        total_in += entries
        total_out += exits
        meals_used += 1
        if meals_used == K_MEALS:
            break

    if meals_used == 0:
        return 1.0, 0               # no history yet: no correction
    return total_in / total_out, meals_used


def estimate_occupancy(hall, now):
    """Everything the website needs to know about one hall at time `now`."""
    display_name, capacity = get_hall(hall)
    result = {"hall": hall, "name": display_name, "capacity": capacity}

    meal = current_meal(now)
    if meal is None:
        result["status"] = "closed"
        return result

    meal_name, start = meal
    entries = count_events(hall, "entrance", start, now)
    exits = count_events(hall, "exit", start, now)
    k, meals_used = correction_factor(hall, meal_name, now)

    people = entries - k * exits
    people = max(0, min(people, capacity))      # keep it between 0 and capacity

    result["status"] = "open"
    result["meal"] = meal_name
    result["entries"] = entries
    result["exits"] = exits
    result["k"] = round(k, 3)
    result["k_meals_used"] = meals_used
    result["people"] = round(people)
    result["percent"] = round(100 * people / capacity)
    return result


# ------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------

@app.post("/event")
async def record_event(
    hall: str,
    lane: Literal["entrance", "exit"],
    time: str | None = None,
    x_api_key: str = Header(default=""),
):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Wrong or missing API key")
    if get_hall(hall) is None:
        raise HTTPException(status_code=404, detail=f"Unknown hall: {hall}")

    if time is None:
        time = datetime.now().isoformat()
    else:
        try:
            time = datetime.fromisoformat(time).isoformat()
        except ValueError:
            raise HTTPException(status_code=400,
                                detail="time must look like 2026-10-28T17:05:00")

    db.execute("INSERT INTO events VALUES (?, ?, ?)", (hall, lane, time))
    db.commit()
    return {"status": "saved", "hall": hall, "lane": lane, "time": time}


@app.get("/occupancy")
async def get_occupancy(hall: str, at: str | None = None):
    if get_hall(hall) is None:
        raise HTTPException(status_code=404, detail=f"Unknown hall: {hall}")
    if at is None:
        now = datetime.now()
    else:
        try:
            now = datetime.fromisoformat(at)
        except ValueError:
            raise HTTPException(status_code=400,
                                detail="at must look like 2026-10-28T18:30:00")
    return estimate_occupancy(hall, now)


@app.get("/status")
async def get_status():
    now = datetime.now()
    halls = db.execute("SELECT name FROM halls ORDER BY display_name").fetchall()
    results = []
    for row in halls:
        results.append(estimate_occupancy(row[0], now))
    return {"updated": now.isoformat(timespec="seconds"), "halls": results}


@app.get("/")
def home_page():
    return FileResponse("index.html")
