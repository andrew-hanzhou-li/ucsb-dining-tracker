"""
Pretends to be the door sensors: sends random entrances and exits to the
running server so you can watch the webpage's bars move.
Stop it with Ctrl+C.
"""
import random
import time
import urllib.request

SERVER = "http://127.0.0.1:8000"
API_KEY = "change-me-to-something-long"     # must match main.py
HALLS = ["portola", "carrillo", "dlg"]

while True:
    hall = random.choice(HALLS)
    if random.random() < 0.6:
        lane = "entrance"
    else:
        lane = "exit"

    url = f"{SERVER}/event?hall={hall}&lane={lane}"
    request = urllib.request.Request(url, method="POST", headers={"X-API-Key": API_KEY})
    urllib.request.urlopen(request)
    print("sent", hall, lane)

    time.sleep(0.3)
