from datetime import datetime

import pytest
from fastapi.testclient import TestClient

import main
from conftest import TEST_KEY

client = TestClient(main.app)


def post_event(key=TEST_KEY, **params):
    headers = {} if key is None else {"X-API-Key": key}
    return client.post("/event", params=params, headers=headers)


def stored_events():
    return main.db.execute("SELECT hall, lane, time FROM events").fetchall()


# ---------------- POST /event ----------------

def test_event_saved_with_given_time():
    r = post_event(hall="portola", lane="entrance", time="2026-10-28T17:05:00")
    assert r.status_code == 200
    assert r.json() == {"status": "saved", "hall": "portola", "lane": "entrance",
                        "time": "2026-10-28T17:05:00"}
    assert stored_events() == [("portola", "entrance", "2026-10-28T17:05:00")]


def test_event_time_is_normalized():
    r = post_event(hall="dlg", lane="exit", time="2026-10-28 17:05")
    assert r.json()["time"] == "2026-10-28T17:05:00"


def test_event_without_time_uses_now():
    before = datetime.now()
    r = post_event(hall="carrillo", lane="exit")
    assert r.status_code == 200
    saved = datetime.fromisoformat(r.json()["time"])
    assert before <= saved <= datetime.now()


@pytest.mark.parametrize("key", [None, "", "wrong-key"])
def test_event_rejects_missing_or_wrong_key(key):
    r = post_event(key=key, hall="portola", lane="entrance")
    assert r.status_code == 401
    assert stored_events() == []


def test_event_unknown_hall():
    r = post_event(hall="ortega", lane="entrance")
    assert r.status_code == 404
    assert stored_events() == []


def test_event_bad_lane():
    r = post_event(hall="portola", lane="window")
    assert r.status_code == 422
    assert stored_events() == []


def test_event_bad_time():
    r = post_event(hall="portola", lane="entrance", time="yesterday")
    assert r.status_code == 400
    assert stored_events() == []


def test_event_hall_name_is_not_sql():
    r = post_event(hall="portola' OR '1'='1", lane="entrance")
    assert r.status_code == 404
    assert stored_events() == []


# ---------------- GET /occupancy ----------------

def test_occupancy_open():
    post_event(hall="portola", lane="entrance", time="2026-10-28T17:10:00")
    r = client.get("/occupancy",
                   params={"hall": "portola", "at": "2026-10-28T18:30:00"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "open"
    assert body["meal"] == "dinner"
    assert body["entries"] == 1
    assert body["people"] == 1


def test_occupancy_closed():
    r = client.get("/occupancy", params={"hall": "dlg", "at": "2026-10-28T16:00:00"})
    assert r.json()["status"] == "closed"


def test_occupancy_unknown_hall():
    r = client.get("/occupancy", params={"hall": "ortega"})
    assert r.status_code == 404


def test_occupancy_bad_time():
    r = client.get("/occupancy", params={"hall": "portola", "at": "soon"})
    assert r.status_code == 400


def test_occupancy_defaults_to_now():
    r = client.get("/occupancy", params={"hall": "portola"})
    assert r.status_code == 200
    assert r.json()["status"] in ("open", "closed")


# ---------------- GET /status ----------------

def test_status_lists_every_hall_by_name(monkeypatch):
    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 10, 28, 18, 30, 0)

    monkeypatch.setattr(main, "datetime", FixedDatetime)
    r = client.get("/status")
    assert r.status_code == 200
    body = r.json()
    assert body["updated"] == "2026-10-28T18:30:00"
    assert [h["name"] for h in body["halls"]] == ["Carrillo", "De La Guerra", "Portola"]
    assert all(h["status"] == "open" and h["meal"] == "dinner" for h in body["halls"])


# ---------------- GET / ----------------

def test_home_page_serves_index_html():
    r = client.get("/")
    assert r.status_code == 200
    assert "How full are the dining halls?" in r.text
