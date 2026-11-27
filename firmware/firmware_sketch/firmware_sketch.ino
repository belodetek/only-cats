/**
 * ESP32 / Seeed XIAO Serial Lock Controller (Normally OFF)
 *
 * Logic:
 *  - Default state: Relay OFF (De-energized / Door Unlocked).
 *  - If 'L' (Lock command) is received, relay energizes (Door LOCKED) and replies "ACK:L".
 *  - If 'U' (Unlock command) is received, relay de-energizes immediately and replies "ACK:U".
 *  - If 'P' (Ping/Heartbeat) is received, replies "ACK:P:LOCKED" or "ACK:P:UNLOCKED".
 *  - If no 'L' command is received for > 3000ms (lockout ends or NUC crashes),
 *    relay immediately turns OFF (Door Unlocked) and emits "EVENT:TIMEOUT_UNLOCK".
 */

#include <Arduino.h>
#include <esp_app_desc.h>

#ifndef FW_VERSION
#define FW_VERSION "dev"
#endif

extern "C" const __attribute__((section(".rodata_desc"))) esp_app_desc_t esp_app_desc = {
    .magic_word = ESP_APP_DESC_MAGIC_WORD,
    .secure_version = 0,
    .reserv1 = {0},
    .version = FW_VERSION,
    .project_name = "only-cats",
    .time = __TIME__,
    .date = __DATE__,
    .idf_ver = IDF_VER,
    .app_elf_sha256 = {0},
};

#if defined(ARDUINO_XIAO_ESP32C3) || defined(ARDUINO_XIAO_ESP32S3) || defined(ARDUINO_SEEED_XIAO_C6) || defined(D2)
const uint8_t RELAY_PIN = D0;
#else
const uint8_t RELAY_PIN = 0;
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

#ifdef QEMU_HIL
#include <esp_task_wdt.h>
#endif

void setup() {
// modify watchdog behaviour under QEMU
#ifdef QEMU_HIL
  esp_task_wdt_config_t wdt_config = {
    .timeout_ms = 30000,
    .idle_core_mask = (1 << portNUM_PROCESSORS) - 1,
    .trigger_panic = false,
  };
  esp_task_wdt_reconfigure(&wdt_config);
#endif

  Serial.begin(115200);
  Serial.setRxFIFOFull(1);

  pinMode(RELAY_PIN, OUTPUT);
  if (LED_PIN >= 0) {
    pinMode(LED_PIN, OUTPUT);
  }

  // DEFAULT STATE: OFF (Unlocked)
  setRelayState(false);

  delay(100);
  Serial.print("READY:ULOCK:");
  Serial.println(FW_VERSION);
}

void loop() {
  // Read incoming serial commands from NUC
  while (Serial.available() > 0) {
    char cmd = static_cast<char>(Serial.read());
    if (cmd == 'L') {
      // Prey active: energize relay to lock and refresh fail-safe timer
      lastLockCommandTime = millis();
      if (!isLocked) {
        setRelayState(true);
      }
      Serial.println("ACK:L");
    } else if (cmd == 'U') {
      // Explicit unlock command
      if (isLocked) {
        setRelayState(false);
      }
      Serial.println("ACK:U");
    } else if (cmd == 'P') {
      // Health ping so host can verify MCU is responsive even when unlocked
      Serial.println(isLocked ? "ACK:P:LOCKED" : "ACK:P:UNLOCKED");
    }
  }

  // Fail-safe timeout: if no 'L' received within 3s, drop back to default OFF (Unlocked)
  if (isLocked && (millis() - lastLockCommandTime > LOCK_TIMEOUT_MS)) {
    setRelayState(false);
    Serial.println("EVENT:TIMEOUT_UNLOCK");
  }
}