/*
 * ChipCheck seeded-fault demo for classic Arduino Nano (ATmega328P).
 *
 * USB serial protocol (115200 baud):
 *   Host -> Nano: H\n
 *   Nano -> Host: READY\n
 *   Host -> Nano: T,<id>,<scenario 1-4>,<led1 0-255>,<led2 0-255>,<led3 0-255>\n
 *   Nano -> Host: R,<id>,P\n or R,<id>,F\n
 *
 * The fault is intentionally injected by this firmware. It does not measure
 * an electrical failure in a real device. Test codes represent 0..3.3 V
 * average-equivalent levels on a 3.3 V Nano. PWM is still a pulse train,
 * not a steady analog voltage.
 */
/*
#include <stdlib.h>
#include <string.h>

const uint8_t LED1_PIN = 3;  // PWM
const uint8_t LED2_PIN = 5;  // PWM
const uint8_t LED3_PIN = 6;  // PWM
const uint8_t BUZZER_SIGNAL_PIN = 9; // Signal input on a buzzer module with its own driver
const uint8_t STATUS_LED_PIN = LED_BUILTIN; // ON means seeded FAIL
const unsigned long SETTLE_MS = 500;
const unsigned long BEEP_ON_MS = 100;
const unsigned long BEEP_GAP_MS = 80;
const unsigned long STATUS_FLASH_MS = 100;
const bool BUZZER_ACTIVE_HIGH = true; // Change to false only for an active-low module

char lineBuffer[64];
uint8_t lineLength = 0;

bool inside(int value, int low, int high) {
  return value >= low && value <= high;
}

bool injectedFailure(int scenario, int a, int b, int c) {
  switch (scenario) {
    case 1: return inside(a, 85, 170) && inside(b, 163, 177) && inside(c, 132, 162);
    case 2: return inside(a, 62, 193) && inside(b, 78, 216) && inside(c, 39, 193);
    case 3: return inside(a, 194, 216) && inside(b, 39, 61) && inside(c, 217, 239);
    case 4: return false; // Control scenario: no injected failure
    default: return false;
  }
}

bool parseUnsigned(char *text, unsigned long &value) {
  if (text == NULL || *text == '\0') return false;
  char *end = NULL;
  value = strtoul(text, &end, 10);
  return end != text && *end == '\0';
}

uint8_t pwmFor3V3Equivalent(uint8_t code) {
  // On a 3.3 V Nano, full PWM scale maps to a 0..3.3 V pulse average.
  return code;
}

void handleLine(char *line) {
  if (strcmp(line, "H") == 0) {
    Serial.println(F("READY"));
    return;
  }

  // Expected fields: T,id,scenario,led1,led2,led3
  char *fields[6];
  uint8_t count = 0;
  char *token = strtok(line, ",");
  while (token != NULL && count < 6) {
    fields[count++] = token;
    token = strtok(NULL, ",");
  }
  if (token != NULL || count != 6 || strcmp(fields[0], "T") != 0) {
    Serial.println(F("ERR,FORMAT"));
    return;
  }

  unsigned long id, scenario, a, b, c;
  if (!parseUnsigned(fields[1], id) || !parseUnsigned(fields[2], scenario) ||
      !parseUnsigned(fields[3], a) || !parseUnsigned(fields[4], b) ||
      !parseUnsigned(fields[5], c) || scenario < 1 || scenario > 4 ||
      a > 255 || b > 255 || c > 255) {
    Serial.println(F("ERR,VALUE"));
    return;
  }

  analogWrite(LED1_PIN, pwmFor3V3Equivalent((uint8_t)a));
  analogWrite(LED2_PIN, pwmFor3V3Equivalent((uint8_t)b));
  analogWrite(LED3_PIN, pwmFor3V3Equivalent((uint8_t)c));
  digitalWrite(STATUS_LED_PIN, HIGH); // brief heartbeat while a test is applied
  delay(60);
  digitalWrite(STATUS_LED_PIN, LOW);
  delay(SETTLE_MS);

  bool failed = injectedFailure((int)scenario, (int)a, (int)b, (int)c);
  // The module's onboard driver handles buzzer current; D9 only drives its signal input.
  if (!failed) {
    // Two short beeps mark a passing test.
    digitalWrite(BUZZER_SIGNAL_PIN, BUZZER_ACTIVE_HIGH ? HIGH : LOW);
    delay(BEEP_ON_MS);
    digitalWrite(BUZZER_SIGNAL_PIN, BUZZER_ACTIVE_HIGH ? LOW : HIGH);
    delay(BEEP_GAP_MS);
    digitalWrite(BUZZER_SIGNAL_PIN, BUZZER_ACTIVE_HIGH ? HIGH : LOW);
    delay(BEEP_ON_MS);
    digitalWrite(BUZZER_SIGNAL_PIN, BUZZER_ACTIVE_HIGH ? LOW : HIGH);
  } else {
    digitalWrite(BUZZER_SIGNAL_PIN, BUZZER_ACTIVE_HIGH ? LOW : HIGH);
    // Three flashes mark a seeded failure, then leave the LED on until next test.
    for (uint8_t flash = 0; flash < 3; ++flash) {
      digitalWrite(STATUS_LED_PIN, HIGH);
      delay(STATUS_FLASH_MS);
      digitalWrite(STATUS_LED_PIN, LOW);
      delay(STATUS_FLASH_MS);
    }
    digitalWrite(STATUS_LED_PIN, HIGH);
  }

  Serial.print(F("R,"));
  Serial.print(id);
  Serial.print(',');
  Serial.println(failed ? 'F' : 'P');
}

void setup() {
  pinMode(LED1_PIN, OUTPUT);
  pinMode(LED2_PIN, OUTPUT);
  pinMode(LED3_PIN, OUTPUT);
  pinMode(BUZZER_SIGNAL_PIN, OUTPUT);
  pinMode(STATUS_LED_PIN, OUTPUT);
  analogWrite(LED1_PIN, 0);
  analogWrite(LED2_PIN, 0);
  analogWrite(LED3_PIN, 0);
  digitalWrite(BUZZER_SIGNAL_PIN, BUZZER_ACTIVE_HIGH ? LOW : HIGH);
  digitalWrite(STATUS_LED_PIN, LOW);
  Serial.begin(115200);
}

void loop() {
  while (Serial.available() > 0) {
    char ch = (char)Serial.read();
    if (ch == '\r') continue;
    if (ch == '\n') {
      lineBuffer[lineLength] = '\0';
      if (lineLength > 0) handleLine(lineBuffer);
      lineLength = 0;
    } else if (lineLength < sizeof(lineBuffer) - 1) {
      lineBuffer[lineLength++] = ch;
    } else {
      lineLength = 0;
      Serial.println(F("ERR,TOO_LONG"));
    }
  }
}
*/
