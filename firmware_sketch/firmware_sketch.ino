/**
 * ESP32 / Seeed XIAO Serial Lock Controller (Normally OFF)
 *
 * Logic:
 *  - Default state: Relay OFF (De-energized / Door Unlocked).
 *  - If 'L' (Lock command) is received, relay energizes (Door LOCKED).
 *  - If no 'L' command is received for > 3000ms (lockout ends or NUC crashes),
 *    relay immediately turns OFF (Door Unlocked).
 */

#include <Arduino.h>

#if defined(ARDUINO_XIAO_ESP32C3) || defined(ARDUINO_XIAO_ESP32S3) || defined(ARDUINO_SEEED_XIAO_C6) || defined(D2)
const uint8_t RELAY_PIN = D2;
#else
const uint8_t RELAY_PIN = 2;
#endif

#if defined(LED_BUILTIN)
const int LED_PIN = LED_BUILTIN;
#else
const int LED_PIN = -1;
#endif

const unsigned long LOCK_TIMEOUT_MS = 3000;

unsigned long lastLockCommandTime = 0;
bool isLocked = false;

void setRelayState(bool energize) {
  isLocked = energize;
  // High-Level Trigger: HIGH energizes coil (Locks door)
  digitalWrite(RELAY_PIN, energize ? HIGH : LOW);

  if (LED_PIN >= 0) {
    digitalWrite(LED_PIN, energize ? LOW : HIGH); // Active-low onboard LED
  }
}

void setup() {
  Serial.begin(115200);

  pinMode(RELAY_PIN, OUTPUT);
  if (LED_PIN >= 0) {
    pinMode(LED_PIN, OUTPUT);
  }

  // DEFAULT STATE: OFF (Unlocked)
  setRelayState(false);

  delay(100);
}

void loop() {
  // Read incoming serial commands from NUC
  while (Serial.available() > 0) {
    char cmd = static_cast<char>(Serial.read());
    if (cmd == 'L') {
      // Prey active: energize relay to lock
      lastLockCommandTime = millis();
      if (!isLocked) {
        setRelayState(true);
      }
    }
  }

  // Timeout: if no 'L' received within 3s, drop back to default OFF (Unlocked)
  if (isLocked && (millis() - lastLockCommandTime > LOCK_TIMEOUT_MS)) {
    setRelayState(false);
  }
}
