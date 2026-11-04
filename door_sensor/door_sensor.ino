// Door sensor for the dining hall tracker.
// Works with a push button (for testing) or an IR break-beam receiver:
// both pull the pin LOW when "someone is there".

#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <time.h>
#include "secrets.h"    // Wi-Fi name/password, SERVER, API_KEY, ROOT_CA

// ---------------- Settings: change these ----------------
const char* HALL          = "portola";
const char* LANE          = "exit";

const int SENSOR_PIN   = 4;     // GPIO pin the button / beam receiver is wired to
// Blocks shorter than MIN_BLOCK_MS are noise (an arm, a swinging bag).
// The beam must be clear for MIN_CLEAR_MS before the next person counts.
const int MIN_BLOCK_MS = 80;
const int MIN_CLEAR_MS = 150;
// ---------------------------------------------------------

bool personPassing = false;       // are we in the middle of someone walking through?
unsigned long blockStart = 0;     // when the beam got blocked
unsigned long clearStart = 0;     // when the beam cleared again (0 = not clear yet)
int eventsSent = 0;

void connectWifi() {
  Serial.print("Connecting to Wi-Fi");
  WiFi.begin(WIFI_NAME, WIFI_PASSWORD);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println();
  Serial.print("Connected! My IP address is ");
  Serial.println(WiFi.localIP());
}

// HTTPS needs the real date to check the server's certificate hasn't expired,
// and the ESP32 has no clock battery, so ask an internet time server.
void syncClock() {
  Serial.print("Getting the time");
  configTime(0, 0, "pool.ntp.org", "time.google.com");
  while (time(nullptr) < 1700000000) {     // any time before late 2023 means "not set yet"
    delay(500);
    Serial.print(".");
  }
  Serial.println(" done");
}

void sendEvent(unsigned long blockedMs) {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("No Wi-Fi, event lost");
    return;
  }
  String url = String(SERVER) + "/event?hall=" + HALL + "&lane=" + LANE;

  // https:// addresses (the VPS) get an encrypted connection that checks the
  // certificate; http:// addresses (your laptop) get a plain one.
  WiFiClientSecure secureClient;
  WiFiClient plainClient;
  HTTPClient http;
  if (url.startsWith("https://")) {
    secureClient.setCACert(ROOT_CA);
    http.begin(secureClient, url);
  } else {
    http.begin(plainClient, url);
  }
  http.addHeader("X-API-Key", API_KEY);
  int code = http.POST("");
  http.end();

  eventsSent++;
  Serial.printf("Person #%d (blocked %lu ms) -> server replied %d\n",
                eventsSent, blockedMs, code);
}

void setup() {
  Serial.begin(115200);
  pinMode(SENSOR_PIN, INPUT_PULLUP);   // pin reads HIGH unless something pulls it LOW
  connectWifi();
  syncClock();
}

void loop() {
  bool blocked = (digitalRead(SENSOR_PIN) == LOW);
  unsigned long now = millis();

  if (!personPassing && blocked) {
    // Beam just got blocked: someone is starting to walk through
    personPassing = true;
    blockStart = now;
    clearStart = 0;
  }
  else if (personPassing && blocked) {
    // Still blocked (or blocked again before it was clear long enough): same person
    clearStart = 0;
  }
  else if (personPassing && !blocked) {
    // Beam is clear. Wait until it has stayed clear for MIN_CLEAR_MS.
    if (clearStart == 0) {
      clearStart = now;
    }
    if (now - clearStart >= MIN_CLEAR_MS) {
      unsigned long blockedMs = clearStart - blockStart;
      personPassing = false;
      if (blockedMs >= MIN_BLOCK_MS) {
        sendEvent(blockedMs);
      } else {
        Serial.printf("Ignored a %lu ms blip\n", blockedMs);
      }
    }
  }
}
