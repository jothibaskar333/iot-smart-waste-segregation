/*
 * ESP32 sensor node - REFERENCE SKETCH (UNTESTED)
 * ------------------------------------------------
 * Status: this sketch has NOT been compiled, flashed, or tested on real
 * hardware. It is a starting point showing how a future ESP32 node could
 * publish readings in the JSON format the dashboard already accepts.
 *
 * Libraries (Arduino Library Manager):
 *   - PubSubClient  (Nick O'Leary)
 *   - ArduinoJson   (Benoit Blanchon, v7)
 *   - ESP32Servo    (Kevin Harrington)
 *
 * Payload published to MQTT_TOPIC (must match the dashboard's MQTT_TOPIC):
 *   {"device_id":"esp32-node-01","ir":true,"moisture":63.2,"metal":false,
 *    "fill":{"wet":42.0,"dry":18.5,"metal":7.0}}
 *
 * Design note: the dashboard classifies every reading it receives. So that
 * the diverter can react without a network round-trip, this node mirrors the
 * same simple rules locally. Keep MOISTURE_THRESHOLD in sync with the value
 * configured on the dashboard.
 *
 * Do not commit real Wi-Fi or MQTT credentials. Replace the placeholder
 * values below only in your local copy, just before flashing.
 */

#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <ESP32Servo.h>

// ---- Credentials: fill in locally, never commit real values -------------
const char* WIFI_SSID     = "YOUR_WIFI_SSID";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";
const char* MQTT_HOST     = "192.168.1.10";   // PC running the broker
const uint16_t MQTT_PORT  = 1883;
const char* MQTT_USER     = "";               // leave empty if not used
const char* MQTT_PASS     = "";
const char* MQTT_TOPIC    = "smartwaste/sensors";
const char* DEVICE_ID     = "esp32-node-01";

// ---- Proposed pin mapping (see README) ------------------------------------
const int PIN_IR          = 27;  // IR obstacle sensor, active LOW
const int PIN_METAL       = 26;  // inductive sensor via optocoupler, active LOW
const int PIN_MOISTURE    = 34;  // capacitive moisture sensor (ADC1, input only)
const int PIN_SERVO       = 13;  // servo signal (servo powered from separate 5 V)
const int TRIG[3]         = {25, 32, 33};  // HC-SR04 trigger: wet, dry, metal
const int ECHO[3]         = {18, 19, 21};  // HC-SR04 echo (5 V -> 3.3 V divider!)

// ---- Calibration: measure these on your own sensors ---------------------
const int   MOISTURE_RAW_DRY   = 3200;   // ADC reading in dry air (example only)
const int   MOISTURE_RAW_WET   = 1300;   // ADC reading in water   (example only)
const float MOISTURE_THRESHOLD = 60.0;   // keep in sync with dashboard
const float BIN_DEPTH_CM       = 30.0;   // sensor-to-bottom distance when empty
const float BIN_FULL_GAP_CM    = 3.0;    // distance that counts as 100 % full

// ---- Servo angles: keep in sync with SERVO_ANGLE_* on the dashboard ------
const int ANGLE_IDLE = 0, ANGLE_WET = 45, ANGLE_DRY = 90, ANGLE_METAL = 135;

WiFiClient wifiClient;
PubSubClient mqtt(wifiClient);
Servo diverter;
bool itemWasPresent = false;

float readMoisturePercent() {
  long sum = 0;
  for (int i = 0; i < 10; i++) { sum += analogRead(PIN_MOISTURE); delay(5); }
  float raw = sum / 10.0;
  float pct = (MOISTURE_RAW_DRY - raw) * 100.0 / (MOISTURE_RAW_DRY - MOISTURE_RAW_WET);
  return constrain(pct, 0.0, 100.0);
}

float readFillPercent(int idx) {
  digitalWrite(TRIG[idx], LOW);  delayMicroseconds(2);
  digitalWrite(TRIG[idx], HIGH); delayMicroseconds(10);
  digitalWrite(TRIG[idx], LOW);
  unsigned long us = pulseIn(ECHO[idx], HIGH, 30000UL);  // ~5 m timeout
  if (us == 0) return -1;                                // no echo
  float cm = us / 58.0;
  float pct = (BIN_DEPTH_CM - cm) * 100.0 / (BIN_DEPTH_CM - BIN_FULL_GAP_CM);
  return constrain(pct, 0.0, 100.0);
}

void connectWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  while (WiFi.status() != WL_CONNECTED) { delay(500); Serial.print('.'); }
  Serial.printf("\nWi-Fi connected, IP %s\n", WiFi.localIP().toString().c_str());
}

void ensureMqtt() {
  while (!mqtt.connected()) {
    bool ok = strlen(MQTT_USER) ? mqtt.connect(DEVICE_ID, MQTT_USER, MQTT_PASS)
                                : mqtt.connect(DEVICE_ID);
    if (!ok) { Serial.printf("MQTT connect failed (%d), retrying\n", mqtt.state()); delay(2000); }
  }
}

void divert(bool metal, float moisture) {
  int angle = metal ? ANGLE_METAL : (moisture > MOISTURE_THRESHOLD ? ANGLE_WET : ANGLE_DRY);
  diverter.write(angle);
  delay(800);                 // let the item drop
  diverter.write(ANGLE_IDLE);
}

void publishReading(bool ir, float moisture, bool metal) {
  JsonDocument doc;
  doc["device_id"] = DEVICE_ID;
  doc["ir"] = ir;
  doc["moisture"] = round(moisture * 10) / 10.0;
  doc["metal"] = metal;
  const char* names[3] = {"wet", "dry", "metal"};
  JsonObject fill = doc["fill"].to<JsonObject>();
  for (int i = 0; i < 3; i++) {
    float pct = readFillPercent(i);
    if (pct >= 0) fill[names[i]] = round(pct * 10) / 10.0;
  }
  char buf[256];
  size_t n = serializeJson(doc, buf);
  mqtt.publish(MQTT_TOPIC, (const uint8_t*)buf, n, false);
  Serial.println(buf);
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_IR, INPUT_PULLUP);
  pinMode(PIN_METAL, INPUT_PULLUP);
  for (int i = 0; i < 3; i++) { pinMode(TRIG[i], OUTPUT); pinMode(ECHO[i], INPUT); }
  diverter.attach(PIN_SERVO);
  diverter.write(ANGLE_IDLE);
  connectWiFi();
  mqtt.setServer(MQTT_HOST, MQTT_PORT);
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) connectWiFi();
  ensureMqtt();
  mqtt.loop();

  bool itemPresent = digitalRead(PIN_IR) == LOW;
  if (itemPresent && !itemWasPresent) {        // rising edge: new item
    delay(300);                                // let the item settle
    float moisture = readMoisturePercent();
    bool metal = digitalRead(PIN_METAL) == LOW;
    publishReading(true, moisture, metal);
    divert(metal, moisture);
  }
  itemWasPresent = itemPresent;
  delay(50);
}
