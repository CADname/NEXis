#include <Arduino.h>
#include <Wire.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <Preferences.h>
#include <WebServer.h>
#include <DNSServer.h>
#include <PubSubClient.h>
#include <time.h>
#include <math.h>
#include "secrets.h"

#ifndef ESP_ARDUINO_VERSION_MAJOR
#define ESP_ARDUINO_VERSION_MAJOR 2
#endif

// ============================================================
// ESP32 Integrated Firmware
// BTS7960 RPM Control + Hall RPM + ADXL345 Vibration
// + ACS712 30A Current + Measurement CSV + Realtime CSV
// ============================================================
// Purpose
// 1. Replace manual knob-based PWM control with ESP32 + BTS7960 target-RPM control
// 2. Read actual RPM from the Hall sensor, search for the matching PWM automatically, then LOCK
// 3. Collect 3-axis vibration data from the ADXL345
// 4. Collect current data from the ACS712 30A sensor
// 5. Exclude acceleration, search, and candidate-evaluation phases from training-data capture
// 6. Start training CSV capture by command after target RPM is locked
// 7. Stream realtime CSV telemetry for the dashboard and inference pipeline
// ============================================================


// ============================================================
// User configuration
// ============================================================

// ---------- ESP32 pin configuration ----------
#define PIN_HALL  32
#define PIN_ACS   36

#define PIN_RPWM  25
#define PIN_LPWM  26
#define PIN_REN   27
#define PIN_LEN   14

#define PIN_I2C_SDA 21
#define PIN_I2C_SCL 22

// ---------- Serial ----------
const uint32_t SERIAL_BAUDRATE = 115200;

// ---------- Wi-Fi manager + direct AWS MQTT TLS transport ----------
// Wi-Fi credentials are stored in ESP32 NVS. No recompile is needed when the AP changes.
// If no saved network can connect, ESP32 opens a captive portal: NEXis-Setup-XXXX / 192.168.4.1
const unsigned long WIFI_CONNECT_TIMEOUT_MS = 8000;
const unsigned long WIFI_RESCAN_INTERVAL_MS = 12000;
const int WIFI_MAX_SAVED = 8;
const int WIFI_MIN_ACCEPTABLE_RSSI = -78;
// WIFI_SETUP_AP_PASSWORD is defined in secrets.h and is not committed.
const unsigned long TCP_RECONNECT_INTERVAL_MS = 3000;
const unsigned long CLOUD_STATUS_INTERVAL_MS = 2000;
const unsigned long CLOUD_HEALTH_INTERVAL_MS = 5000;
const unsigned long REMOTE_FAILSAFE_MS = 5000;
const int REMOTE_RPM_MIN = 100;
const int REMOTE_RPM_MAX = 1500;
const int MQTT_BATCH_SAMPLES = 10;

WiFiClientSecure mqttTlsClient;
PubSubClient mqttClient(mqttTlsClient);
unsigned long lastTcpReconnectMs = 0;
unsigned long lastCloudStatusMs = 0;
unsigned long lastCloudHealthMs = 0;
unsigned long mqttDisconnectedSinceMs = 0;
bool wifiReady = false;
bool remoteControlEnabled = true; // Enable AWS remote command reception at boot. Motor start still requires server-side arming
bool remoteControlActive = false;
String lastCloudCommandId = "";
String mqttBatchBody = "";
int mqttBatchCount = 0;
unsigned long mqttBatchSeq = 0;

// ---------- persistent multi-Wi-Fi / captive portal ----------
struct SavedWiFiNetwork {
  String ssid;
  String password;
  int priority; // 1 = highest priority
};

Preferences wifiPrefs;
WebServer wifiPortal(80);
DNSServer wifiDns;
SavedWiFiNetwork savedWiFi[WIFI_MAX_SAVED];
int savedWiFiCount = 0;
bool wifiPortalActive = false;
bool wifiPortalRoutesReady = false;
bool wifiPortalStartPending = false;
bool wifiConnectRequested = false;
unsigned long wifiPortalStartRequestedMs = 0;
unsigned long wifiConnectRequestedMs = 0;
unsigned long lastWiFiReconnectAttemptMs = 0;
String wifiSetupApName = "";
String lastConnectedSsid = "";

// ---------- ADXL345 ----------
#define ADXL345_ADDR 0x53
#define REG_DEVID       0x00
#define REG_POWER_CTL   0x2D
#define REG_DATA_FORMAT 0x31
#define REG_BW_RATE     0x2C
#define REG_DATAX0      0x32

const float ADXL345_SCALE_G_PER_LSB = 0.0039f;

// ---------- Data output intervals ----------
const unsigned long SAMPLE_INTERVAL_MS = 10;
const unsigned long LIVE_STATUS_INTERVAL_MS = 250;

// ---------- Measurement mode ----------
const unsigned long MEASUREMENT_DURATION_MS = 10000;
const unsigned long MEASUREMENT_LOCK_SETTLE_MS = 1200;
const float MEASUREMENT_MAX_RPM_ERROR = 10.0f;

// ---------- Realtime CSV streaming ----------
const bool REALTIME_STREAM_ONLY_WHEN_TARGET_SET = false;
const bool CLOUD_TELEMETRY_ALWAYS_ON = true;     // Send sensor telemetry to AWS even at RPM=0/IDLE
const bool PRINT_REALTIME_CSV_TO_SERIAL = false; // Prevent 100 Hz serial flooding; training-measurement CSV output remains enabled

// ---------- PWM configuration ----------
const int PWM_FREQ = 20000;
const int PWM_RESOLUTION = 10;
const int PWM_DUTY_MAX = (1 << PWM_RESOLUTION) - 1;

const float PWM_EQ_MAX = 255.0f;
const float PWM_LIMIT_EQ = 130.0f;

const float PWM_FAST_START_LIMIT_EQ = 40.0f;
const float PWM_FAST_START_STEP_EQ = 5.0f;
const float PWM_APPROACH_STEP_EQ = 1.25f;

const float CANDIDATE_SEEK_STEP_COARSE_EQ = 0.50f;
const float CANDIDATE_SEEK_STEP_FINE_EQ = 0.25f;
const float CANDIDATE_SEEK_FINE_ERROR_RPM = 50.0f;

const int CANDIDATE_SCAN_COUNT = 3;

const unsigned long CONTROL_INTERVAL_MS = 200;
const unsigned long PWM_CHANGE_COOLDOWN_MS = 350;

const unsigned long SEEK_HOLD_MS = 5000;
const unsigned long SEEK_IGNORE_MS = 2500;
const int SEEK_MIN_SAMPLES = 6;

const unsigned long CANDIDATE_HOLD_MS = 5000;
const unsigned long CANDIDATE_IGNORE_MS = 2500;
const int CANDIDATE_MIN_SAMPLES = 6;

const unsigned long TARGET_RAMP_HOLD_MS = 1400;
const unsigned long TARGET_RAMP_IGNORE_MS = 600;
const int TARGET_RAMP_MIN_SAMPLES = 3;
const float TARGET_RAMP_UP_STEP_EQ = 0.50f;
const float TARGET_RAMP_DOWN_STEP_EQ = 0.50f;
const float TARGET_RAMP_TO_SEEK_ERROR_RPM = 80.0f;

const float CANDIDATE_ACCEPT_ERROR_RPM = 15.0f;

const float TARGET_BAND_RPM = 5.0f;
const float ACCEL_ZONE_BELOW_RPM = 160.0f;
const float CANDIDATE_ENTRY_ERROR_RPM = 130.0f;
const int CANDIDATE_SEEK_MAX_STEPS = 80;
const float RPM_FILTER_ALPHA = 0.10f;

// ---------- Stable-RPM detection for fast convergence ----------
// Adjust PWM quickly when actual RPM is more than ±100 RPM from the target.
// Ignore transient RPM spikes and sudden zero readings when making control decisions.
const float FAST_CONVERGE_BAND_RPM = 120.0f;
const float FAST_CONVERGE_UP_STEP_EQ = 2.00f;
const float FAST_CONVERGE_DOWN_STEP_EQ = 1.50f;

// ---------- Fast precision LOCK configuration ----------
// Near the target, do not force long fixed-duration evaluation of three candidates.
// Evaluate a short neighborhood around the current PWM and keep the PWM with the lowest mean RPM error.
// After LOCK, keep PWM fixed.
const float PRECISION_ENTRY_ERROR_RPM = 70.0f;
const float PRECISION_COARSE_ERROR_RPM = 160.0f;
const float PRECISION_MID_ERROR_RPM = 45.0f;
const float PRECISION_NEAR_ERROR_RPM = 18.0f;

const float PRECISION_COARSE_STEP_EQ = 2.00f;
const float PRECISION_MID_STEP_EQ = 1.00f;
const float PRECISION_FINE_STEP_EQ = 0.25f;

const unsigned long PRECISION_HOLD_MS = 1100;
const unsigned long PRECISION_IGNORE_MS = 350;
const int PRECISION_MIN_SAMPLES = 4;

const int PRECISION_MIN_EVAL_BEFORE_LOCK = 4;
const int PRECISION_MAX_EVAL_COUNT = 18;
const int PRECISION_NO_IMPROVE_LIMIT = 3;
const float PRECISION_IMPROVE_MARGIN_RPM = 0.30f;
const float PRECISION_EXCELLENT_ERROR_RPM = 2.0f;

const int CONTROL_RPM_MIN_VALID_SAMPLES = 4;
const float CONTROL_RPM_MIN_VALID_VALUE = 30.0f;

// Soft stop
const unsigned long SOFT_STOP_DURATION_MS = 1000;

// ---------- Hall sensor RPM ----------
const float PULSES_PER_REV = 1.0f;
const unsigned long MIN_PULSE_INTERVAL_US = 20000;
const unsigned long STOP_TIMEOUT_US = 700000;
const int RPM_AVG_N = 12;

// ---------- ACS712 30A ----------
float ACS_ZERO_VOLTAGE = 2.254f;
float ACS_SENSITIVITY = 0.066f;
const float ADC_REF = 3.3f;
const int ADC_MAX = 4095;

// Current protection thresholds
const float CURRENT_SLOWDOWN_A = 18.0f;
const float CURRENT_STRONG_DOWN_A = 20.0f;
const float PWM_CURRENT_DOWN_STEP_EQ = 1.00f;
const float PWM_CURRENT_STRONG_DOWN_STEP_EQ = 2.00f;


// ============================================================
// Enums / state variables
// ============================================================

enum ControlMode {
  MODE_IDLE,
  MODE_ACCEL,
  MODE_TARGET_RAMP,
  MODE_TRACK,
  MODE_SEEK_HOLD,
  MODE_CANDIDATE_HOLD,
  MODE_LOCK
};

enum DataMode {
  DATA_IDLE,
  DATA_MEASUREMENT_ARMED,
  DATA_MEASURING,
  DATA_REALTIME_STREAM
};

ControlMode controlMode = MODE_IDLE;
DataMode dataMode = DATA_IDLE;

String inputLine = "";
String tcpInputLine = "";

// ---------- RPM ISR state ----------
volatile unsigned long lastPulseTimeUs = 0;
volatile unsigned long pulseIntervalUs = 0;
volatile bool newPulse = false;

float rpmBuffer[RPM_AVG_N];
int rpmIndex = 0;
int rpmCount = 0;

float currentRPM = 0.0f;
float filteredRPM = 0.0f;

// ---------- Control state ----------
int targetRPM = 0;
float pwmNowEq = 0.0f;
float lockPwmEq = 0.0f;

bool motorEnabled = false;
bool softStopping = false;
unsigned long softStopStartMs = 0;
float softStopStartPwmEq = 0.0f;

unsigned long lastControlMs = 0;
unsigned long lastPwmChangeMs = 0;
unsigned long lastStatusMs = 0;

// ---------- Averaging state ----------
unsigned long measureStartMs = 0;
float measureRpmSum = 0.0f;
int measureRpmCount = 0;
float measureRpmMin = 999999.0f;
float measureRpmMax = -999999.0f;

// ---------- Candidate-search state ----------
bool lowValid = false;
bool highValid = false;

float lowPwmEq = 0.0f;
float highPwmEq = 0.0f;

float lowAvgRPM = 0.0f;
float highAvgRPM = 0.0f;

float lowAbsError = 999999.0f;
float highAbsError = 999999.0f;

int seekStepCount = 0;
int seekDirection = 0;

float candidatePwmEq[CANDIDATE_SCAN_COUNT] = {0.0f, 0.0f, 0.0f};
float candidateAvgRPM[CANDIDATE_SCAN_COUNT] = {0.0f, 0.0f, 0.0f};
float candidateAbsError[CANDIDATE_SCAN_COUNT] = {999999.0f, 999999.0f, 999999.0f};
int candidateIndex = 0;

bool bestValid = false;
float bestPwmEq = 0.0f;
float bestAvgRPM = 0.0f;
float bestAbsError = 999999.0f;

bool nearestAnyValid = false;
float nearestAnyPwmEq = 0.0f;
float nearestAnyAvgRPM = 0.0f;
float nearestAnyAbsError = 999999.0f;

bool blockLowerSideValid = false;
float blockLowerThanPwmEq = 0.0f;

bool blockHigherSideValid = false;
float blockHigherThanPwmEq = 0.0f;

// ---------- Fast precision LOCK state ----------
bool precisionBestValid = false;
float precisionBestPwmEq = 0.0f;
float precisionBestAvgRPM = 0.0f;
float precisionBestAbsError = 999999.0f;

bool precisionLowValid = false;
float precisionLowPwmEq = 0.0f;
float precisionLowAvgRPM = 0.0f;
float precisionLowAbsError = 999999.0f;

bool precisionHighValid = false;
float precisionHighPwmEq = 0.0f;
float precisionHighAvgRPM = 0.0f;
float precisionHighAbsError = 999999.0f;

int precisionEvalCount = 0;
int precisionNoImproveCount = 0;
bool precisionInterpolationTried = false;

// ---------- Data-capture state ----------
int conditionNumber = -1;
char stateLabel[16] = "normal";
char faultTypeLabel[24] = "none";

unsigned long dataStartMs = 0;
unsigned long previousSampleMs = 0;
unsigned long armedLockStartMs = 0;
uint32_t sampleIndex = 0;

bool csvHeaderPrintedMeasurement = false;
bool csvHeaderPrintedRealtime = false;


// ============================================================
// Function declarations
// ============================================================

const char* modeName(ControlMode mode);
const char* dataModeName(DataMode mode);

void printBootMessage();
void printHelp();
void printStatusLine();

void setupWiFiClient();
void maintainTcpConnection();
void loadSavedWiFi();
void persistSavedWiFi();
bool saveWiFiCredential(const String &ssid, const String &password, int priority);
bool deleteWiFiCredential(const String &ssid);
bool connectBestSavedWiFi();
void maintainWiFiConnection();
void requestWiFiSetupPortal();
void startWiFiSetupPortal();
void stopWiFiSetupPortal();
void serviceWiFiSetupPortal();
void printSavedWiFi();
void syncClockForTls();
void sendLineBoth(const String &line);
void sendCsvLine(const String &line);

void writeRegister(byte reg, byte value);
byte readRegister(byte reg);
bool readAccelRaw(int16_t &xRaw, int16_t &yRaw, int16_t &zRaw);
bool setupADXL345();

void setupPWM();
void writeRPWM(int duty);
void writeLPWM(int duty);
int pwmEqToDuty10Bit(float pwmEq);
void motorApplyForward(float pwmEq);
void motorHardOff();
void beginSoftStop();
void handleSoftStop();
bool setPWM(float pwmEq);
bool canChangePWM();

void IRAM_ATTR hallISR();
void resetRPMBuffer();
float getAverageRPM();
void updateRPM();
bool getControlStableRPM(float &stableRPM);

float readAcsVoltage();
float readCurrentA();

void resetMeasurementAverage();
float getMeasurementAverage();
float rpmForMeasurement();
void addMeasurementSample(unsigned long elapsed, unsigned long ignoreMs, unsigned long holdMs);

void resetCandidateState();
void updateLowHigh(float avgRPM, float pwmEq);
void updateBestCandidate(float pwmEq, float avgRPM);
bool isCandidateBlockedBy15Rule(float pwmEq);
float getCandidateSeekStepEq(float avgRPM);
float estimateTargetPwm();
void buildThreeCandidates();
void startSeekHold();
void startCandidateSeeking();
void startCandidateHold();
void moveSeekNext(float avgRPM);

void resetPrecisionLockState();
float getBlindStartSoftCeilingEq();
void updatePrecisionBest(float pwmEq, float avgRPM);
float getPrecisionStepEq(float absError);
float estimatePrecisionInterpolatedPwm();
void lockToPrecisionBest(const char* reason);
void startPrecisionEvaluate();

void setTargetRPM(int rpmInput);
void controlRPM();

void resetConditionLabel();
bool setConditionLabel(int condition);
void armMeasurement(int condition);
void cancelMeasurement();
void startMeasurementNow();
void stopMeasurementFinished();
void startRealtimeStream();
void stopRealtimeStream();
void handleMeasurementArmed();
void handleDataOutput();
void printMeasurementHeader();
void printRealtimeHeader();
void printCsvRow(bool withLabel);

void handleCommand(String cmd);
bool parseManualPWMCommand(String cmd, float &manualPwmEq);
bool parseMeasureCommand(String cmd, int &condition);
bool parseTargetRPMCommand(String cmd, int &rpmValue);
void readSerialInput();
void readTcpInput();
void mqttCallback(char* topic, byte* payload, unsigned int length);
void publishControlStatus(const char* reason = "periodic");
void publishCloudHealth();
void queueCloudTelemetry(unsigned long sampleIdx, unsigned long nowMs, float ax, float ay, float az, float totalG, float rpm, int target, float rpmErr, float pwmEq, int duty10, float acsV, float currentA, const char* mode);
void flushCloudTelemetry();
void handleCloudFailSafe();


// ============================================================
// Wi-Fi + direct AWS MQTT TLS transport
// ============================================================

String mqttTopic(const char* suffix) {
  String t = MQTT_TOPIC_PREFIX;
  t += suffix;
  return t;
}

String htmlEscape(const String &input) {
  String out;
  out.reserve(input.length() + 16);
  for (unsigned int i = 0; i < input.length(); i++) {
    char c = input.charAt(i);
    if (c == '&') out += "&amp;";
    else if (c == '<') out += "&lt;";
    else if (c == '>') out += "&gt;";
    else if (c == '"') out += "&quot;";
    else if (c == '\'') out += "&#39;";
    else out += c;
  }
  return out;
}

void loadSavedWiFi() {
  savedWiFiCount = 0;
  wifiPrefs.begin("nexis_wifi", true);
  int count = wifiPrefs.getInt("count", 0);
  if (count < 0) count = 0;
  if (count > WIFI_MAX_SAVED) count = WIFI_MAX_SAVED;
  for (int i = 0; i < count; i++) {
    String ks = "ssid" + String(i);
    String kp = "pass" + String(i);
    String kr = "prio" + String(i);
    String ssid = wifiPrefs.getString(ks.c_str(), "");
    if (ssid.length() == 0) continue;
    savedWiFi[savedWiFiCount].ssid = ssid;
    savedWiFi[savedWiFiCount].password = wifiPrefs.getString(kp.c_str(), "");
    savedWiFi[savedWiFiCount].priority = wifiPrefs.getInt(kr.c_str(), savedWiFiCount + 1);
    if (savedWiFi[savedWiFiCount].priority < 1) savedWiFi[savedWiFiCount].priority = 1;
    savedWiFiCount++;
  }
  wifiPrefs.end();
}

void persistSavedWiFi() {
  wifiPrefs.begin("nexis_wifi", false);
  wifiPrefs.clear();
  wifiPrefs.putInt("count", savedWiFiCount);
  for (int i = 0; i < savedWiFiCount; i++) {
    String ks = "ssid" + String(i);
    String kp = "pass" + String(i);
    String kr = "prio" + String(i);
    wifiPrefs.putString(ks.c_str(), savedWiFi[i].ssid);
    wifiPrefs.putString(kp.c_str(), savedWiFi[i].password);
    wifiPrefs.putInt(kr.c_str(), savedWiFi[i].priority);
  }
  wifiPrefs.end();
}

bool saveWiFiCredential(const String &ssidIn, const String &password, int priority) {
  String ssid = ssidIn;
  ssid.trim();
  if (ssid.length() == 0 || ssid.length() > 32) return false;
  if (priority < 1) priority = 1;
  if (priority > 99) priority = 99;
  for (int i = 0; i < savedWiFiCount; i++) {
    if (savedWiFi[i].ssid == ssid) {
      savedWiFi[i].password = password;
      savedWiFi[i].priority = priority;
      persistSavedWiFi();
      return true;
    }
  }
  if (savedWiFiCount >= WIFI_MAX_SAVED) {
    int replaceIndex = 0;
    for (int i = 1; i < savedWiFiCount; i++) {
      if (savedWiFi[i].priority > savedWiFi[replaceIndex].priority) replaceIndex = i;
    }
    savedWiFi[replaceIndex].ssid = ssid;
    savedWiFi[replaceIndex].password = password;
    savedWiFi[replaceIndex].priority = priority;
  } else {
    savedWiFi[savedWiFiCount].ssid = ssid;
    savedWiFi[savedWiFiCount].password = password;
    savedWiFi[savedWiFiCount].priority = priority;
    savedWiFiCount++;
  }
  persistSavedWiFi();
  return true;
}

bool deleteWiFiCredential(const String &ssid) {
  for (int i = 0; i < savedWiFiCount; i++) {
    if (savedWiFi[i].ssid == ssid) {
      for (int j = i; j < savedWiFiCount - 1; j++) savedWiFi[j] = savedWiFi[j + 1];
      savedWiFiCount--;
      persistSavedWiFi();
      return true;
    }
  }
  return false;
}

void printSavedWiFi() {
  Serial.print("# WIFI_SAVED_COUNT=");
  Serial.println(savedWiFiCount);
  for (int i = 0; i < savedWiFiCount; i++) {
    Serial.print("# WIFI_SAVED["); Serial.print(i); Serial.print("] PRIORITY=");
    Serial.print(savedWiFi[i].priority); Serial.print(" SSID="); Serial.println(savedWiFi[i].ssid);
  }
}

void syncClockForTls() {
  if (WiFi.status() != WL_CONNECTED) return;
  configTime(0, 0, "pool.ntp.org", "time.nist.gov");
  unsigned long ntpStart = millis();
  while (time(nullptr) < 1700000000 && millis() - ntpStart < 10000) delay(250);
  Serial.print("# NTP_TIME_VALID=");
  Serial.println(time(nullptr) >= 1700000000 ? "YES" : "NO");
}

bool connectBestSavedWiFi() {
  loadSavedWiFi();
  if (savedWiFiCount <= 0) {
    Serial.println("# WIFI_NO_SAVED_NETWORKS");
    return false;
  }

  WiFi.mode(wifiPortalActive ? WIFI_AP_STA : WIFI_STA);
  WiFi.setSleep(false);
  WiFi.disconnect(false, false);
  delay(150);
  Serial.println("# WIFI_SCAN_START");
  int found = WiFi.scanNetworks(false, true);
  if (found <= 0) {
    Serial.println("# WIFI_SCAN_NONE");
    WiFi.scanDelete();
    return false;
  }

  struct Candidate { int savedIndex; int rssi; bool strong; } candidates[WIFI_MAX_SAVED];
  int candidateCount = 0;
  for (int i = 0; i < savedWiFiCount; i++) {
    int bestRssi = -1000;
    for (int n = 0; n < found; n++) {
      if (WiFi.SSID(n) == savedWiFi[i].ssid && WiFi.RSSI(n) > bestRssi) bestRssi = WiFi.RSSI(n);
    }
    if (bestRssi > -1000) {
      candidates[candidateCount].savedIndex = i;
      candidates[candidateCount].rssi = bestRssi;
      candidates[candidateCount].strong = bestRssi >= WIFI_MIN_ACCEPTABLE_RSSI;
      candidateCount++;
    }
  }
  WiFi.scanDelete();
  if (candidateCount <= 0) {
    Serial.println("# WIFI_NO_SAVED_NETWORK_VISIBLE");
    return false;
  }

  // Strong candidates: priority first, then RSSI. If every saved AP is weak, strongest wins.
  bool anyStrong = false;
  for (int i = 0; i < candidateCount; i++) if (candidates[i].strong) anyStrong = true;
  for (int i = 0; i < candidateCount - 1; i++) {
    for (int j = i + 1; j < candidateCount; j++) {
      int ai = candidates[i].savedIndex, aj = candidates[j].savedIndex;
      bool swapNeeded = false;
      if (anyStrong) {
        if (candidates[i].strong != candidates[j].strong) swapNeeded = (!candidates[i].strong && candidates[j].strong);
        else if (candidates[i].strong && candidates[j].strong) {
          if (savedWiFi[aj].priority < savedWiFi[ai].priority) swapNeeded = true;
          else if (savedWiFi[aj].priority == savedWiFi[ai].priority && candidates[j].rssi > candidates[i].rssi) swapNeeded = true;
        } else if (candidates[j].rssi > candidates[i].rssi) swapNeeded = true;
      } else if (candidates[j].rssi > candidates[i].rssi) swapNeeded = true;
      if (swapNeeded) { Candidate tmp = candidates[i]; candidates[i] = candidates[j]; candidates[j] = tmp; }
    }
  }

  for (int c = 0; c < candidateCount; c++) {
    int i = candidates[c].savedIndex;
    Serial.print("# WIFI_TRY SSID="); Serial.print(savedWiFi[i].ssid);
    Serial.print(" PRIORITY="); Serial.print(savedWiFi[i].priority);
    Serial.print(" RSSI="); Serial.println(candidates[c].rssi);
    WiFi.begin(savedWiFi[i].ssid.c_str(), savedWiFi[i].password.c_str());
    unsigned long startMs = millis();
    while (WiFi.status() != WL_CONNECTED && millis() - startMs < WIFI_CONNECT_TIMEOUT_MS) delay(250);
    if (WiFi.status() == WL_CONNECTED) {
      wifiReady = true;
      lastConnectedSsid = WiFi.SSID();
      Serial.print("# WIFI_CONNECTED SSID="); Serial.print(WiFi.SSID());
      Serial.print(" IP="); Serial.print(WiFi.localIP());
      Serial.print(" RSSI="); Serial.println(WiFi.RSSI());
      syncClockForTls();
      return true;
    }
    WiFi.disconnect(false, false);
    delay(100);
  }
  Serial.println("# WIFI_ALL_SAVED_CONNECTIONS_FAILED");
  return false;
}

String wifiPortalHtml() {
  String h;
  h.reserve(9000);
  h += "<!doctype html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'>";
  h += "<title>NEXis Wi-Fi Setup</title><style>body{font-family:Arial,sans-serif;max-width:760px;margin:30px auto;padding:0 16px;background:#0b1220;color:#e8eef9}h1{font-size:26px}.card{background:#131d2e;border:1px solid #29364a;border-radius:12px;padding:16px;margin:14px 0}input,select,button{font-size:16px;padding:10px;margin:5px 0;border-radius:8px;border:1px solid #475569}input,select{width:100%;box-sizing:border-box;background:#0f172a;color:#fff}button{background:#2563eb;color:#fff;cursor:pointer}.danger{background:#b91c1c}.ok{color:#86efac}.muted{color:#94a3b8}table{width:100%;border-collapse:collapse}td,th{padding:7px;border-bottom:1px solid #263348;text-align:left}</style></head><body>";
  h += "<h1>NEXis Wi-Fi Setup</h1><div class='card'><b>Device:</b> " + htmlEscape(wifiSetupApName) + "<br>";
  if (WiFi.status() == WL_CONNECTED) h += "<span class='ok'>Connected: " + htmlEscape(WiFi.SSID()) + " / " + WiFi.localIP().toString() + " / RSSI " + String(WiFi.RSSI()) + " dBm</span>";
  else h += "<span class='muted'>No Internet Wi-Fi connected</span>";
  h += "</div><div class='card'><h3>Add or update network</h3><form method='POST' action='/save'>";
  h += "SSID<input name='ssid' maxlength='32' required placeholder='Wi-Fi SSID'>Password<input name='password' type='password' maxlength='64' placeholder='Wi-Fi password'>Priority (1 = highest)<input name='priority' type='number' min='1' max='99' value='1'><button type='submit'>Save & Connect</button></form></div>";
  h += "<div class='card'><h3>Saved networks</h3><table><tr><th>Priority</th><th>SSID</th><th></th></tr>";
  for (int i = 0; i < savedWiFiCount; i++) {
    h += "<tr><td>" + String(savedWiFi[i].priority) + "</td><td>" + htmlEscape(savedWiFi[i].ssid) + "</td><td><form method='POST' action='/delete'><input type='hidden' name='ssid' value=\"" + htmlEscape(savedWiFi[i].ssid) + "\"><button class='danger' type='submit'>Delete</button></form></td></tr>";
  }
  h += "</table></div><div class='card'><h3>Visible networks</h3>";
  int n = WiFi.scanNetworks(false, true);
  if (n <= 0) h += "<span class='muted'>No networks found.</span>";
  else {
    h += "<table><tr><th>SSID</th><th>RSSI</th><th>Security</th></tr>";
    for (int i = 0; i < n; i++) {
      String ssid = WiFi.SSID(i);
      if (ssid.length() == 0) continue;
      h += "<tr><td>" + htmlEscape(ssid) + "</td><td>" + String(WiFi.RSSI(i)) + " dBm</td><td>" + String(WiFi.encryptionType(i) == WIFI_AUTH_OPEN ? "Open" : "Secured") + "</td></tr>";
    }
    h += "</table>";
  }
  WiFi.scanDelete();
  h += "</div><div class='card'><form method='POST' action='/clear'><button class='danger' type='submit'>Delete ALL saved Wi-Fi</button></form><form method='POST' action='/reboot'><button type='submit'>Reboot ESP32</button></form></div>";
  h += "<p class='muted'>The motor stays locally controlled. AWS connection resumes automatically after Wi-Fi reconnects.</p></body></html>";
  return h;
}

void configureWiFiPortalRoutes() {
  if (wifiPortalRoutesReady) return;
  wifiPortalRoutesReady = true;
  wifiPortal.on("/", HTTP_GET, [](){ wifiPortal.send(200, "text/html; charset=utf-8", wifiPortalHtml()); });
  wifiPortal.on("/save", HTTP_POST, [](){
    String ssid = wifiPortal.arg("ssid");
    String password = wifiPortal.arg("password");
    int priority = wifiPortal.arg("priority").toInt();
    if (saveWiFiCredential(ssid, password, priority)) {
      wifiPortal.send(200, "text/html; charset=utf-8", "<html><body><h2>Saved.</h2><p>NEXis will reconnect automatically in a moment. You may close this page.</p><a href='/'>Back</a></body></html>");
      wifiConnectRequested = true;
      wifiConnectRequestedMs = millis();
      lastWiFiReconnectAttemptMs = 0;
    } else wifiPortal.send(400, "text/plain", "Invalid SSID");
  });
  wifiPortal.on("/delete", HTTP_POST, [](){
    deleteWiFiCredential(wifiPortal.arg("ssid"));
    wifiPortal.sendHeader("Location", "/"); wifiPortal.send(303, "text/plain", "");
  });
  wifiPortal.on("/clear", HTTP_POST, [](){
    savedWiFiCount = 0; persistSavedWiFi();
    wifiPortal.sendHeader("Location", "/"); wifiPortal.send(303, "text/plain", "");
  });
  wifiPortal.on("/reboot", HTTP_POST, [](){ wifiPortal.send(200, "text/plain", "Rebooting..."); delay(300); ESP.restart(); });
  wifiPortal.on("/generate_204", HTTP_ANY, [](){ wifiPortal.sendHeader("Location", "/"); wifiPortal.send(302, "text/plain", ""); });
  wifiPortal.on("/hotspot-detect.html", HTTP_ANY, [](){ wifiPortal.sendHeader("Location", "/"); wifiPortal.send(302, "text/plain", ""); });
  wifiPortal.on("/fwlink", HTTP_ANY, [](){ wifiPortal.sendHeader("Location", "/"); wifiPortal.send(302, "text/plain", ""); });
  wifiPortal.onNotFound([](){ wifiPortal.sendHeader("Location", "/"); wifiPortal.send(302, "text/plain", ""); });
}

void requestWiFiSetupPortal() {
  if (wifiPortalActive || wifiPortalStartPending) return;
  wifiPortalStartPending = true;
  wifiPortalStartRequestedMs = millis();
  Serial.println("# WIFI_SETUP_PORTAL_REQUESTED");
}

void startWiFiSetupPortal() {
  if (wifiPortalActive) return;
  wifiPortalStartPending = false;

  uint64_t chipId = ESP.getEfuseMac();
  char suffix[9]; snprintf(suffix, sizeof(suffix), "%08X", (uint32_t)chipId);
  wifiSetupApName = "NEXis-Setup-" + String(suffix + 4);

  // Wi-Fi driver mode changes are staged deliberately. On some classic ESP32
  // DevKitC boards an immediate STA -> AP_STA transition during setup() can
  // trigger the task watchdog. Starting the portal from loop() after boot and
  // yielding between driver transitions avoids that reset loop.
  Serial.println("# WIFI_PORTAL_STEP=RADIO_OFF");
  WiFi.disconnect(true, false);
  delay(150);
  yield();
  WiFi.mode(WIFI_OFF);
  delay(200);
  yield();

  Serial.println("# WIFI_PORTAL_STEP=AP_MODE");
  WiFi.mode(WIFI_AP);
  delay(250);
  yield();

  IPAddress apIp(192, 168, 4, 1);
  IPAddress apGw(192, 168, 4, 1);
  IPAddress apMask(255, 255, 255, 0);
  WiFi.softAPConfig(apIp, apGw, apMask);

  Serial.println("# WIFI_PORTAL_STEP=SOFTAP_START");
  bool apOk = WiFi.softAP(wifiSetupApName.c_str(), WIFI_SETUP_AP_PASSWORD, 6, false, 4);
  delay(200);
  yield();
  if (!apOk) {
    Serial.println("# WIFI_SETUP_PORTAL_START_FAILED_RETRY_LATER");
    WiFi.softAPdisconnect(true);
    WiFi.mode(WIFI_OFF);
    wifiPortalStartPending = true;
    wifiPortalStartRequestedMs = millis();
    return;
  }

  configureWiFiPortalRoutes();
  wifiDns.start(53, "*", WiFi.softAPIP());
  wifiPortal.begin();
  wifiPortalActive = true;
  Serial.print("# WIFI_SETUP_PORTAL AP="); Serial.print(wifiSetupApName);
  Serial.print(" SECURITY=WPA2");
  Serial.print(" URL=http://"); Serial.println(WiFi.softAPIP());
}

void stopWiFiSetupPortal() {
  wifiPortalStartPending = false;
  if (!wifiPortalActive) return;
  wifiDns.stop();
  wifiPortal.stop();
  delay(50);
  WiFi.softAPdisconnect(true);
  wifiPortalActive = false;
  WiFi.mode(WIFI_OFF);
  delay(150);
  Serial.println("# WIFI_SETUP_PORTAL_STOPPED");
}

void serviceWiFiSetupPortal() {
  if (!wifiPortalActive) return;
  wifiDns.processNextRequest();
  wifiPortal.handleClient();
  yield();
}

void maintainWiFiConnection() {
  serviceWiFiSetupPortal();

  // Finish an HTTP /save response before changing Wi-Fi mode. Then close the
  // setup AP and connect using the newly saved STA credentials.
  if (wifiConnectRequested && millis() - wifiConnectRequestedMs >= 700) {
    wifiConnectRequested = false;
    if (wifiPortalActive) stopWiFiSetupPortal();
    lastWiFiReconnectAttemptMs = 0;
  }

  if (WiFi.status() == WL_CONNECTED) {
    if (!wifiReady) {
      wifiReady = true;
      lastConnectedSsid = WiFi.SSID();
      Serial.print("# WIFI_RECONNECTED SSID="); Serial.print(WiFi.SSID());
      Serial.print(" IP="); Serial.println(WiFi.localIP());
      syncClockForTls();
    }
    return; // Never roam while the current AP is healthy.
  }

  wifiReady = false;
  if (mqttClient.connected()) mqttClient.disconnect();

  // Do not start the captive portal from setup(). Give the Arduino loop and
  // Wi-Fi system task time to run first.
  if (wifiPortalStartPending) {
    if (millis() - wifiPortalStartRequestedMs >= 1200) startWiFiSetupPortal();
    return;
  }

  if (wifiPortalActive) return;

  unsigned long now = millis();
  if (now - lastWiFiReconnectAttemptMs < WIFI_RESCAN_INTERVAL_MS && !wifiConnectRequested) return;
  lastWiFiReconnectAttemptMs = now;

  if (remoteControlActive) {
    Serial.println("# REMOTE_FAILSAFE_WIFI_LOST_SOFT_STOP");
    remoteControlActive = false;
    beginSoftStop();
  }

  if (!connectBestSavedWiFi()) requestWiFiSetupPortal();
}

void setupWiFiClient() {
  WiFi.persistent(false);
  WiFi.setAutoReconnect(false);
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);

  mqttTlsClient.setCACert(MQTT_CA_CERT);
  mqttClient.setServer(MQTT_HOST, MQTT_PORT);
  mqttClient.setCallback(mqttCallback);
  mqttClient.setBufferSize(8192);
  mqttClient.setKeepAlive(20);
  mqttClient.setSocketTimeout(5);

  loadSavedWiFi();
  printSavedWiFi();
  // Defer Wi-Fi radio transitions until loop() is running. This avoids a
  // TG1WDT reset seen on the Higenis/DevKitC V4 when no credentials exist.
  lastWiFiReconnectAttemptMs = millis() - WIFI_RESCAN_INTERVAL_MS;
  if (savedWiFiCount <= 0) requestWiFiSetupPortal();
}

void maintainTcpConnection() {
  maintainWiFiConnection();
  if (WiFi.status() != WL_CONNECTED) {
    wifiReady = false;
    if (mqttClient.connected()) mqttClient.disconnect();
    return;
  }
  wifiReady = true;
  if (mqttClient.connected()) {
    mqttDisconnectedSinceMs = 0;
    return;
  }
  if (mqttDisconnectedSinceMs == 0) mqttDisconnectedSinceMs = millis();
  unsigned long now = millis();
  if (now - lastTcpReconnectMs < TCP_RECONNECT_INTERVAL_MS) return;
  lastTcpReconnectMs = now;
  uint64_t chipId = ESP.getEfuseMac();
  char clientId[48];
  snprintf(clientId, sizeof(clientId), "nexis-esp32-%04X%08X", (uint16_t)(chipId >> 32), (uint32_t)chipId);
  Serial.print("# MQTT_TLS_CONNECTING TO=");
  Serial.print(MQTT_HOST);
  Serial.print(":");
  Serial.println(MQTT_PORT);
  if (mqttClient.connect(clientId, MQTT_USERNAME, MQTT_PASSWORD)) {
    String cmdTopic = mqttTopic("/control/command");
    mqttClient.subscribe(cmdTopic.c_str(), 1);
    mqttDisconnectedSinceMs = 0;
    Serial.print("# MQTT_CONNECTED SUB=");
    Serial.println(cmdTopic);
    publishControlStatus("mqtt_connected");
    publishCloudHealth();
  } else {
    Serial.print("# MQTT_CONNECT_FAILED STATE=");
    Serial.println(mqttClient.state());
  }
}

void sendLineBoth(const String &line) { Serial.println(line); }
void sendCsvLine(const String &line) { Serial.println(line); }

void mqttCallback(char* topic, byte* payload, unsigned int length) {
  String msg; msg.reserve(length + 1);
  for (unsigned int i = 0; i < length; i++) msg += (char)payload[i];
  int p1 = msg.indexOf('|');
  int p2 = p1 >= 0 ? msg.indexOf('|', p1 + 1) : -1;
  int p3 = p2 >= 0 ? msg.indexOf('|', p2 + 1) : -1;
  if (p1 < 0 || p2 < 0 || p3 < 0) {
    Serial.println("# CLOUD_COMMAND_REJECT_BAD_FORMAT"); publishControlStatus("bad_format"); return;
  }
  String action = msg.substring(0, p1);
  int rpm = msg.substring(p1 + 1, p2).toInt();
  String commandId = msg.substring(p2 + 1, p3);
  action.toUpperCase();
  if (commandId == lastCloudCommandId) { Serial.println("# CLOUD_COMMAND_DUPLICATE_IGNORED"); return; }
  lastCloudCommandId = commandId;
  if (action == "STOP") {
    remoteControlActive = false; beginSoftStop(); Serial.println("# CLOUD_STOP_ACCEPTED"); publishControlStatus("stop_accepted"); return;
  }
  if (action == "SET_RPM") {
    if (!remoteControlEnabled) { Serial.println("# CLOUD_SET_RPM_REJECT_LOCAL_REMOTE_OFF"); publishControlStatus("local_remote_off"); return; }
    if (rpm < REMOTE_RPM_MIN || rpm > REMOTE_RPM_MAX) { Serial.println("# CLOUD_SET_RPM_REJECT_RANGE"); publishControlStatus("rpm_out_of_range"); return; }
    remoteControlActive = true;
    setTargetRPM(rpm);
    startRealtimeStream();
    Serial.print("# CLOUD_SET_RPM_ACCEPTED="); Serial.println(rpm);
    publishControlStatus("set_rpm_accepted");
    return;
  }
  Serial.println("# CLOUD_COMMAND_REJECT_UNKNOWN_ACTION"); publishControlStatus("unknown_action");
}

void publishControlStatus(const char* reason) {
  if (!mqttClient.connected()) return;
  String payload; payload.reserve(420);
  payload += "{\"asset_id\":\"rotor_rig_01\",\"site_id\":\"nexis_lab\",\"remote_enabled\":";
  payload += remoteControlEnabled ? "true" : "false";
  payload += ",\"remote_active\":"; payload += remoteControlActive ? "true" : "false";
  payload += ",\"target_rpm\":" + String(targetRPM);
  payload += ",\"rpm\":" + String(currentRPM, 2);
  payload += ",\"pwm_eq\":" + String(pwmNowEq, 2);
  payload += ",\"control_mode\":\"" + String(modeName(controlMode)) + "\"";
  payload += ",\"mqtt_connected\":true,\"wifi_rssi\":" + String(WiFi.RSSI());
  payload += ",\"reason\":\"" + String(reason) + "\",\"firmware\":\"NEXis-AWS-Physical-v1.4.0\"}";
  String topic = mqttTopic("/control/status"); mqttClient.publish(topic.c_str(), payload.c_str(), false);
}

void publishCloudHealth() {
  if (!mqttClient.connected()) return;
  String payload; payload.reserve(320);
  payload += "{\"asset_id\":\"rotor_rig_01\",\"site_id\":\"nexis_lab\",\"state\":\"ONLINE\",\"hostname\":\"esp32\",\"mqtt_connected\":true";
  payload += ",\"wifi_rssi\":" + String(WiFi.RSSI()) + ",\"uptime_ms\":" + String(millis());
  payload += ",\"firmware\":\"NEXis-AWS-Physical-v1.4.0\"}";
  String topic = mqttTopic("/health"); mqttClient.publish(topic.c_str(), payload.c_str(), false);
}

void queueCloudTelemetry(unsigned long sampleIdx, unsigned long nowMs, float ax, float ay, float az, float totalG, float rpm, int target, float rpmErr, float pwmEq, int duty10, float acsV, float currentA, const char* mode) {
  if (!mqttClient.connected()) return;
  String row; row.reserve(280);
  row += "{\"sample_index\":" + String(sampleIdx) + ",\"time_ms\":" + String(nowMs);
  row += ",\"ax_g\":" + String(ax, 5) + ",\"ay_g\":" + String(ay, 5) + ",\"az_g\":" + String(az, 5);
  row += ",\"total_g\":" + String(totalG, 5) + ",\"rpm\":" + String(rpm, 2) + ",\"target_rpm\":" + String(target);
  row += ",\"rpm_error\":" + String(rpmErr, 2) + ",\"pwm_eq\":" + String(pwmEq, 2) + ",\"duty_10bit\":" + String(duty10);
  row += ",\"acs_v\":" + String(acsV, 4) + ",\"current_a\":" + String(currentA, 4) + ",\"control_mode\":\"" + String(mode) + "\"}";
  if (mqttBatchCount > 0) mqttBatchBody += ',';
  mqttBatchBody += row; mqttBatchCount++;
  if (mqttBatchCount >= MQTT_BATCH_SAMPLES || mqttBatchBody.length() > 6200) flushCloudTelemetry();
}

void flushCloudTelemetry() {
  if (mqttBatchCount <= 0) return;
  if (!mqttClient.connected()) { mqttBatchBody = ""; mqttBatchCount = 0; return; }
  String payload; payload.reserve(mqttBatchBody.length() + 180);
  payload += "{\"asset_id\":\"rotor_rig_01\",\"site_id\":\"nexis_lab\",\"batch_seq\":" + String(mqttBatchSeq++);
  payload += ",\"sample_count\":" + String(mqttBatchCount) + ",\"samples\":[" + mqttBatchBody + "]}";
  String topic = mqttTopic("/telemetry/batch");
  if (!mqttClient.publish(topic.c_str(), payload.c_str(), false)) Serial.println("# MQTT_TELEMETRY_BATCH_PUBLISH_FAILED");
  mqttBatchBody = ""; mqttBatchCount = 0;
}

void handleCloudFailSafe() {
  maintainTcpConnection();
  if (mqttClient.connected()) {
    mqttClient.loop(); mqttDisconnectedSinceMs = 0;
  } else if (remoteControlActive) {
    if (mqttDisconnectedSinceMs == 0) mqttDisconnectedSinceMs = millis();
    if (millis() - mqttDisconnectedSinceMs >= REMOTE_FAILSAFE_MS) {
      Serial.println("# REMOTE_FAILSAFE_MQTT_LOST_SOFT_STOP"); remoteControlActive = false; beginSoftStop();
    }
  }
  unsigned long now = millis();
  if (mqttClient.connected() && now - lastCloudStatusMs >= CLOUD_STATUS_INTERVAL_MS) { lastCloudStatusMs = now; publishControlStatus("periodic"); }
  if (mqttClient.connected() && now - lastCloudHealthMs >= CLOUD_HEALTH_INTERVAL_MS) { lastCloudHealthMs = now; publishCloudHealth(); }
}

void readTcpInput() { if (mqttClient.connected()) mqttClient.loop(); }

// ============================================================
// Name conversion
// ============================================================

const char* modeName(ControlMode mode) {
  switch (mode) {
    case MODE_IDLE: return "IDLE";
    case MODE_ACCEL: return "ACCEL";
    case MODE_TARGET_RAMP: return "TARGET_RAMP";
    case MODE_TRACK: return "TRACK";
    case MODE_SEEK_HOLD: return "SEEK_HOLD";
    case MODE_CANDIDATE_HOLD: return "CANDIDATE_HOLD";
    case MODE_LOCK: return "LOCK";
    default: return "UNKNOWN";
  }
}

const char* dataModeName(DataMode mode) {
  switch (mode) {
    case DATA_IDLE: return "DATA_IDLE";
    case DATA_MEASUREMENT_ARMED: return "DATA_MEASUREMENT_ARMED";
    case DATA_MEASURING: return "DATA_MEASURING";
    case DATA_REALTIME_STREAM: return "DATA_REALTIME_STREAM";
    default: return "DATA_UNKNOWN";
  }
}


// ============================================================
// ADXL345
// ============================================================

void writeRegister(byte reg, byte value) {
  Wire.beginTransmission(ADXL345_ADDR);
  Wire.write(reg);
  Wire.write(value);
  Wire.endTransmission();
}

byte readRegister(byte reg) {
  Wire.beginTransmission(ADXL345_ADDR);
  Wire.write(reg);
  Wire.endTransmission(false);
  Wire.requestFrom(ADXL345_ADDR, 1);

  if (Wire.available()) {
    return Wire.read();
  }

  return 0;
}

bool readAccelRaw(int16_t &xRaw, int16_t &yRaw, int16_t &zRaw) {
  Wire.beginTransmission(ADXL345_ADDR);
  Wire.write(REG_DATAX0);
  Wire.endTransmission(false);
  Wire.requestFrom(ADXL345_ADDR, 6);

  if (Wire.available() == 6) {
    byte x0 = Wire.read();
    byte x1 = Wire.read();
    byte y0 = Wire.read();
    byte y1 = Wire.read();
    byte z0 = Wire.read();
    byte z1 = Wire.read();

    xRaw = (int16_t)((x1 << 8) | x0);
    yRaw = (int16_t)((y1 << 8) | y0);
    zRaw = (int16_t)((z1 << 8) | z0);

    return true;
  }

  return false;
}

bool setupADXL345() {
  byte deviceID = readRegister(REG_DEVID);

  if (deviceID != 0xE5) {
    Serial.print("# ADXL345_DEVICE_ID_ERROR READ=0x");
    Serial.println(deviceID, HEX);
    return false;
  }

  writeRegister(REG_BW_RATE, 0x0A);
  writeRegister(REG_DATA_FORMAT, 0x08);
  writeRegister(REG_POWER_CTL, 0x08);
  delay(100);

  Serial.println("# ADXL345_READY_100HZ_FULL_RES");
  return true;
}


// ============================================================
// PWM / Motor
// ============================================================

int pwmEqToDuty10Bit(float pwmEq) {
  pwmEq = constrain(pwmEq, 0.0f, PWM_EQ_MAX);
  float dutyFloat = pwmEq * ((float)PWM_DUTY_MAX / PWM_EQ_MAX);
  int duty = (int)(dutyFloat + 0.5f);
  duty = constrain(duty, 0, PWM_DUTY_MAX);
  return duty;
}

void setupPWM() {
#if ESP_ARDUINO_VERSION_MAJOR >= 3
  ledcAttach(PIN_RPWM, PWM_FREQ, PWM_RESOLUTION);
  ledcAttach(PIN_LPWM, PWM_FREQ, PWM_RESOLUTION);
#else
  ledcSetup(0, PWM_FREQ, PWM_RESOLUTION);
  ledcSetup(1, PWM_FREQ, PWM_RESOLUTION);
  ledcAttachPin(PIN_RPWM, 0);
  ledcAttachPin(PIN_LPWM, 1);
#endif
}

void writeRPWM(int duty) {
  duty = constrain(duty, 0, PWM_DUTY_MAX);
#if ESP_ARDUINO_VERSION_MAJOR >= 3
  ledcWrite(PIN_RPWM, duty);
#else
  ledcWrite(0, duty);
#endif
}

void writeLPWM(int duty) {
  duty = constrain(duty, 0, PWM_DUTY_MAX);
#if ESP_ARDUINO_VERSION_MAJOR >= 3
  ledcWrite(PIN_LPWM, duty);
#else
  ledcWrite(1, duty);
#endif
}

void motorApplyForward(float pwmEq) {
  pwmEq = constrain(pwmEq, 0.0f, PWM_LIMIT_EQ);
  pwmNowEq = pwmEq;

  digitalWrite(PIN_REN, HIGH);
  digitalWrite(PIN_LEN, HIGH);

  if (pwmNowEq <= 0.0f) {
    writeRPWM(0);
    writeLPWM(0);
    return;
  }

  int duty = pwmEqToDuty10Bit(pwmNowEq);
  writeRPWM(duty);
  writeLPWM(0);
}

void motorHardOff() {
  pwmNowEq = 0.0f;
  lockPwmEq = 0.0f;
  targetRPM = 0;
  motorEnabled = false;
  softStopping = false;
  controlMode = MODE_IDLE;

  resetCandidateState();
  resetRPMBuffer();

  writeRPWM(0);
  writeLPWM(0);
  digitalWrite(PIN_REN, LOW);
  digitalWrite(PIN_LEN, LOW);

  if (dataMode == DATA_MEASURING || dataMode == DATA_MEASUREMENT_ARMED) {
    cancelMeasurement();
  }
}

void beginSoftStop() {
  if (dataMode == DATA_MEASURING || dataMode == DATA_MEASUREMENT_ARMED) {
    cancelMeasurement();
  }

  targetRPM = 0;
  motorEnabled = false;
  controlMode = MODE_IDLE;
  resetCandidateState();

  if (pwmNowEq <= 0.0f) {
    motorHardOff();
    Serial.println("# MOTOR_STOP_ALREADY_ZERO");
    return;
  }

  softStopping = true;
  softStopStartMs = millis();
  softStopStartPwmEq = pwmNowEq;

  digitalWrite(PIN_REN, HIGH);
  digitalWrite(PIN_LEN, HIGH);

  Serial.print("# SOFT_STOP_STARTED_FROM_PWM_EQ=");
  Serial.println(softStopStartPwmEq, 2);
}

void handleSoftStop() {
  if (!softStopping) {
    return;
  }

  unsigned long now = millis();
  unsigned long elapsed = now - softStopStartMs;

  if (elapsed >= SOFT_STOP_DURATION_MS) {
    motorHardOff();
    Serial.println("# SOFT_STOP_DONE");
    return;
  }

  float ratio = 1.0f - ((float)elapsed / (float)SOFT_STOP_DURATION_MS);
  float nextPwmEq = softStopStartPwmEq * ratio;
  if (nextPwmEq < 0.0f) {
    nextPwmEq = 0.0f;
  }

  motorApplyForward(nextPwmEq);
}

bool canChangePWM() {
  unsigned long now = millis();
  return (now - lastPwmChangeMs >= PWM_CHANGE_COOLDOWN_MS);
}

bool setPWM(float pwmEq) {
  pwmEq = constrain(pwmEq, 0.0f, PWM_LIMIT_EQ);

  if (fabsf(pwmEq - pwmNowEq) < 0.001f) {
    motorApplyForward(pwmEq);
    return true;
  }

  motorApplyForward(pwmEq);
  lastPwmChangeMs = millis();
  return true;
}


// ============================================================
// Hall RPM
// ============================================================

void IRAM_ATTR hallISR() {
  unsigned long nowUs = micros();

  if (lastPulseTimeUs == 0) {
    lastPulseTimeUs = nowUs;
    return;
  }

  unsigned long dt = nowUs - lastPulseTimeUs;

  if (dt >= MIN_PULSE_INTERVAL_US) {
    pulseIntervalUs = dt;
    lastPulseTimeUs = nowUs;
    newPulse = true;
  }
}

void resetRPMBuffer() {
  noInterrupts();
  lastPulseTimeUs = 0;
  pulseIntervalUs = 0;
  newPulse = false;
  interrupts();

  rpmIndex = 0;
  rpmCount = 0;
  currentRPM = 0.0f;
  filteredRPM = 0.0f;

  for (int i = 0; i < RPM_AVG_N; i++) {
    rpmBuffer[i] = 0.0f;
  }
}

float getAverageRPM() {
  if (rpmCount == 0) {
    return 0.0f;
  }

  float sum = 0.0f;
  for (int i = 0; i < rpmCount; i++) {
    sum += rpmBuffer[i];
  }
  return sum / (float)rpmCount;
}

void updateRPM() {
  noInterrupts();
  bool hasNewPulse = newPulse;
  unsigned long intervalCopy = pulseIntervalUs;
  unsigned long lastPulseCopy = lastPulseTimeUs;
  newPulse = false;
  interrupts();

  if (hasNewPulse && intervalCopy > 0) {
    float periodSec = intervalCopy / 1000000.0f;
    float rpmInstant = 60.0f / (periodSec * PULSES_PER_REV);

    if (rpmInstant > 0.0f && rpmInstant < 10000.0f) {
      rpmBuffer[rpmIndex] = rpmInstant;
      rpmIndex = (rpmIndex + 1) % RPM_AVG_N;
      if (rpmCount < RPM_AVG_N) {
        rpmCount++;
      }
    }
  }

  unsigned long nowUs = micros();

  if (lastPulseCopy != 0 && (nowUs - lastPulseCopy > STOP_TIMEOUT_US)) {
    rpmIndex = 0;
    rpmCount = 0;
    currentRPM = 0.0f;
    filteredRPM = 0.0f;
    return;
  }

  float rpmAvg = getAverageRPM();

  if (rpmAvg <= 0.0f) {
    currentRPM = 0.0f;
    return;
  }

  if (filteredRPM <= 1.0f) {
    filteredRPM = rpmAvg;
  } else {
    filteredRPM = RPM_FILTER_ALPHA * rpmAvg + (1.0f - RPM_FILTER_ALPHA) * filteredRPM;
  }

  currentRPM = filteredRPM;
}

bool getControlStableRPM(float &stableRPM) {
  if (rpmCount < CONTROL_RPM_MIN_VALID_SAMPLES) {
    return false;
  }

  float sum = 0.0f;
  float minValue = 999999.0f;
  float maxValue = -999999.0f;
  int validCount = 0;

  for (int i = 0; i < rpmCount; i++) {
    float r = rpmBuffer[i];

    if (r >= CONTROL_RPM_MIN_VALID_VALUE && r < 10000.0f) {
      sum += r;
      validCount++;

      if (r < minValue) {
        minValue = r;
      }

      if (r > maxValue) {
        maxValue = r;
      }
    }
  }

  if (validCount < CONTROL_RPM_MIN_VALID_SAMPLES) {
    return false;
  }

  if (validCount >= 6) {
    float trimmedSum = sum - minValue - maxValue;
    int trimmedCount = validCount - 2;

    if (trimmedCount > 0) {
      stableRPM = trimmedSum / (float)trimmedCount;
      return true;
    }
  }

  stableRPM = sum / (float)validCount;
  return true;
}


// ============================================================
// ACS712
// ============================================================

float readAcsVoltage() {
  long sum = 0;
  const int N = 40;

  for (int i = 0; i < N; i++) {
    sum += analogRead(PIN_ACS);
    delayMicroseconds(80);
  }

  float adc = sum / (float)N;
  return adc * ADC_REF / ADC_MAX;
}

float readCurrentA() {
  float v = readAcsVoltage();
  return (v - ACS_ZERO_VOLTAGE) / ACS_SENSITIVITY;
}


// ============================================================
// Measurement averaging utilities
// ============================================================

void resetMeasurementAverage() {
  measureStartMs = millis();
  measureRpmSum = 0.0f;
  measureRpmCount = 0;
  measureRpmMin = 999999.0f;
  measureRpmMax = -999999.0f;
}

float getMeasurementAverage() {
  if (measureRpmCount <= 0) {
    return currentRPM;
  }

  if (measureRpmCount >= 6) {
    float trimmedSum = measureRpmSum - measureRpmMin - measureRpmMax;
    int trimmedCount = measureRpmCount - 2;

    if (trimmedCount > 0) {
      return trimmedSum / (float)trimmedCount;
    }
  }

  return measureRpmSum / (float)measureRpmCount;
}

float rpmForMeasurement() {
  float avg = getAverageRPM();
  if (avg > 0.0f) {
    return avg;
  }
  return currentRPM;
}

void addMeasurementSample(unsigned long elapsed, unsigned long ignoreMs, unsigned long holdMs) {
  if (elapsed >= ignoreMs && elapsed < holdMs) {
    float r = rpmForMeasurement();

    if (r > 0.0f) {
      measureRpmSum += r;
      measureRpmCount++;

      if (r < measureRpmMin) {
        measureRpmMin = r;
      }

      if (r > measureRpmMax) {
        measureRpmMax = r;
      }
    }
  }
}


// ============================================================
// Candidate search
// ============================================================

void resetCandidateState() {
  lowValid = false;
  highValid = false;

  lowPwmEq = 0.0f;
  highPwmEq = 0.0f;

  lowAvgRPM = 0.0f;
  highAvgRPM = 0.0f;

  lowAbsError = 999999.0f;
  highAbsError = 999999.0f;

  seekStepCount = 0;
  seekDirection = 0;

  for (int i = 0; i < CANDIDATE_SCAN_COUNT; i++) {
    candidatePwmEq[i] = 0.0f;
    candidateAvgRPM[i] = 0.0f;
    candidateAbsError[i] = 999999.0f;
  }

  candidateIndex = 0;

  bestValid = false;
  bestPwmEq = 0.0f;
  bestAvgRPM = 0.0f;
  bestAbsError = 999999.0f;

  nearestAnyValid = false;
  nearestAnyPwmEq = 0.0f;
  nearestAnyAvgRPM = 0.0f;
  nearestAnyAbsError = 999999.0f;

  blockLowerSideValid = false;
  blockLowerThanPwmEq = 0.0f;

  blockHigherSideValid = false;
  blockHigherThanPwmEq = 0.0f;

  resetPrecisionLockState();
}

void updateLowHigh(float avgRPM, float pwmEq) {
  float signedError = (float)targetRPM - avgRPM;
  float absError = fabsf(signedError);

  if (signedError > 0.0f) {
    if (!lowValid || absError < lowAbsError) {
      lowValid = true;
      lowPwmEq = pwmEq;
      lowAvgRPM = avgRPM;
      lowAbsError = absError;

      Serial.print("# LOW_CANDIDATE_UPDATED PWM_EQ=");
      Serial.print(lowPwmEq, 2);
      Serial.print(" AVG_RPM=");
      Serial.print(lowAvgRPM, 1);
      Serial.print(" ERR=");
      Serial.println(lowAbsError, 1);
    }
  } else if (signedError < 0.0f) {
    if (!highValid || absError < highAbsError) {
      highValid = true;
      highPwmEq = pwmEq;
      highAvgRPM = avgRPM;
      highAbsError = absError;

      Serial.print("# HIGH_CANDIDATE_UPDATED PWM_EQ=");
      Serial.print(highPwmEq, 2);
      Serial.print(" AVG_RPM=");
      Serial.print(highAvgRPM, 1);
      Serial.print(" ERR=");
      Serial.println(highAbsError, 1);
    }
  } else {
    lowValid = true;
    highValid = true;
    lowPwmEq = pwmEq;
    highPwmEq = pwmEq;
    lowAvgRPM = avgRPM;
    highAvgRPM = avgRPM;
    lowAbsError = 0.0f;
    highAbsError = 0.0f;
  }
}

void updateBestCandidate(float pwmEq, float avgRPM) {
  float signedRpmError = avgRPM - (float)targetRPM;
  float err = fabsf(signedRpmError);

  if (!nearestAnyValid || err < nearestAnyAbsError) {
    nearestAnyValid = true;
    nearestAnyPwmEq = pwmEq;
    nearestAnyAvgRPM = avgRPM;
    nearestAnyAbsError = err;
  }

  if (signedRpmError < -CANDIDATE_ACCEPT_ERROR_RPM) {
    if (!blockLowerSideValid || pwmEq > blockLowerThanPwmEq) {
      blockLowerSideValid = true;
      blockLowerThanPwmEq = pwmEq;
      Serial.print("# BLOCK_LOWER_SIDE_FROM_PWM PWM_EQ=");
      Serial.print(blockLowerThanPwmEq, 2);
      Serial.print(" AVG_RPM=");
      Serial.print(avgRPM, 1);
      Serial.print(" ERR=");
      Serial.println(signedRpmError, 1);
    }
  }

  if (signedRpmError > CANDIDATE_ACCEPT_ERROR_RPM) {
    if (!blockHigherSideValid || pwmEq < blockHigherThanPwmEq) {
      blockHigherSideValid = true;
      blockHigherThanPwmEq = pwmEq;
      Serial.print("# BLOCK_HIGHER_SIDE_FROM_PWM PWM_EQ=");
      Serial.print(blockHigherThanPwmEq, 2);
      Serial.print(" AVG_RPM=");
      Serial.print(avgRPM, 1);
      Serial.print(" ERR=");
      Serial.println(signedRpmError, 1);
    }
  }

  if (err > CANDIDATE_ACCEPT_ERROR_RPM) {
    Serial.print("# CANDIDATE_EXCLUDED_OVER_15RPM PWM_EQ=");
    Serial.print(pwmEq, 2);
    Serial.print(" AVG_RPM=");
    Serial.print(avgRPM, 1);
    Serial.print(" ERR=");
    Serial.println(err, 1);
    return;
  }

  if (!bestValid || err < bestAbsError) {
    bestValid = true;
    bestPwmEq = pwmEq;
    bestAvgRPM = avgRPM;
    bestAbsError = err;

    Serial.print("# BEST_FINAL_CANDIDATE_STRICT_MIN_ERROR PWM_EQ=");
    Serial.print(bestPwmEq, 2);
    Serial.print(" AVG_RPM=");
    Serial.print(bestAvgRPM, 1);
    Serial.print(" ERR=");
    Serial.println(bestAbsError, 1);
  } else {
    Serial.print("# BEST_KEEP_CURRENT_STRICT_MIN_ERROR CURRENT_PWM=");
    Serial.print(pwmEq, 2);
    Serial.print(" CURRENT_ERR=");
    Serial.print(err, 1);
    Serial.print(" BEST_PWM=");
    Serial.print(bestPwmEq, 2);
    Serial.print(" BEST_ERR=");
    Serial.println(bestAbsError, 1);
  }
}

bool isCandidateBlockedBy15Rule(float pwmEq) {
  if (blockLowerSideValid && pwmEq < blockLowerThanPwmEq - 0.001f) {
    return true;
  }

  if (blockHigherSideValid && pwmEq > blockHigherThanPwmEq + 0.001f) {
    return true;
  }

  return false;
}

float getCandidateSeekStepEq(float avgRPM) {
  float absError = fabsf((float)targetRPM - avgRPM);
  if (absError > CANDIDATE_SEEK_FINE_ERROR_RPM) {
    return CANDIDATE_SEEK_STEP_COARSE_EQ;
  }
  return CANDIDATE_SEEK_STEP_FINE_EQ;
}

float estimateTargetPwm() {
  if (!lowValid || !highValid) {
    return pwmNowEq;
  }

  if (fabsf(highAvgRPM - lowAvgRPM) < 0.001f) {
    return (lowPwmEq + highPwmEq) * 0.5f;
  }

  float ratio = ((float)targetRPM - lowAvgRPM) / (highAvgRPM - lowAvgRPM);
  ratio = constrain(ratio, 0.0f, 1.0f);

  float estimated = lowPwmEq + (highPwmEq - lowPwmEq) * ratio;
  estimated = constrain(estimated, min(lowPwmEq, highPwmEq), max(lowPwmEq, highPwmEq));
  return estimated;
}

void buildThreeCandidates() {
  float est = estimateTargetPwm();

  candidatePwmEq[0] = lowPwmEq;
  candidatePwmEq[1] = est;
  candidatePwmEq[2] = highPwmEq;

  for (int i = 0; i < CANDIDATE_SCAN_COUNT; i++) {
    candidatePwmEq[i] = constrain(candidatePwmEq[i], 0.0f, PWM_LIMIT_EQ);
    candidateAvgRPM[i] = 0.0f;
    candidateAbsError[i] = 999999.0f;
  }

  candidateIndex = 0;

  Serial.print("# BUILD_3_CANDIDATES LOW_PWM=");
  Serial.print(candidatePwmEq[0], 2);
  Serial.print(" EST_PWM=");
  Serial.print(candidatePwmEq[1], 2);
  Serial.print(" HIGH_PWM=");
  Serial.println(candidatePwmEq[2], 2);
}

void startSeekHold() {
  resetMeasurementAverage();
  resetRPMBuffer();
  controlMode = MODE_SEEK_HOLD;

  Serial.print("# SEEK_HOLD_START PWM_EQ=");
  Serial.print(pwmNowEq, 2);
  Serial.print(" TARGET=");
  Serial.println(targetRPM);
}

void startCandidateSeeking() {
  resetCandidateState();

  Serial.print("# START_CANDIDATE_SEEKING PWM_EQ=");
  Serial.print(pwmNowEq, 2);
  Serial.print(" RPM=");
  Serial.print(currentRPM, 1);
  Serial.print(" TARGET=");
  Serial.println(targetRPM);

  startSeekHold();
}

void startCandidateHold() {
  while (candidateIndex < CANDIDATE_SCAN_COUNT && isCandidateBlockedBy15Rule(candidatePwmEq[candidateIndex])) {
    Serial.print("# CANDIDATE_SKIPPED_BY_15RPM_SIDE_RULE INDEX=");
    Serial.print(candidateIndex + 1);
    Serial.print("/");
    Serial.print(CANDIDATE_SCAN_COUNT);
    Serial.print(" PWM_EQ=");
    Serial.println(candidatePwmEq[candidateIndex], 2);
    candidateIndex++;
  }

  if (candidateIndex >= CANDIDATE_SCAN_COUNT) {
    if (bestValid) {
      lockPwmEq = bestPwmEq;
      controlMode = MODE_LOCK;
      motorApplyForward(lockPwmEq);

      Serial.print("# FINAL_LOCK_ONE_PWM_FROM_3_CANDIDATES_WITHIN_15RPM LOCK_PWM_EQ=");
      Serial.print(lockPwmEq, 2);
      Serial.print(" BEST_AVG_RPM=");
      Serial.print(bestAvgRPM, 1);
      Serial.print(" BEST_ERR=");
      Serial.println(bestAbsError, 1);
      return;
    }

    Serial.println("# NO_CANDIDATE_WITHIN_15RPM_RESEEK");

    if (nearestAnyValid) {
      float signedError = (float)targetRPM - nearestAnyAvgRPM;
      float nextPwm = nearestAnyPwmEq;
      float stepEq = getCandidateSeekStepEq(nearestAnyAvgRPM);

      if (signedError > 0.0f) {
        nextPwm = nearestAnyPwmEq + stepEq;
      } else if (signedError < 0.0f) {
        nextPwm = nearestAnyPwmEq - stepEq;
      }

      setPWM(nextPwm);
    }

    startCandidateSeeking();
    return;
  }

  float pwm = candidatePwmEq[candidateIndex];
  setPWM(pwm);
  resetMeasurementAverage();
  resetRPMBuffer();
  controlMode = MODE_CANDIDATE_HOLD;

  Serial.print("# CANDIDATE_HOLD_START INDEX=");
  Serial.print(candidateIndex + 1);
  Serial.print("/");
  Serial.print(CANDIDATE_SCAN_COUNT);
  Serial.print(" PWM_EQ=");
  Serial.println(pwm, 2);
}

void moveSeekNext(float avgRPM) {
  float signedError = (float)targetRPM - avgRPM;

  if (signedError > 0.0f) {
    seekDirection = 1;
  } else if (signedError < 0.0f) {
    seekDirection = -1;
  } else {
    seekDirection = 0;
  }

  if (seekDirection == 0) {
    lowValid = true;
    highValid = true;
    lowPwmEq = pwmNowEq;
    highPwmEq = pwmNowEq;
    lowAvgRPM = avgRPM;
    highAvgRPM = avgRPM;
    lowAbsError = 0.0f;
    highAbsError = 0.0f;
    buildThreeCandidates();
    startCandidateHold();
    return;
  }

  if (seekStepCount >= CANDIDATE_SEEK_MAX_STEPS) {
    Serial.println("# SEEK_MAX_STEPS_REACHED_LOCK_BEST_AVAILABLE");

    if (lowValid || highValid) {
      if (lowValid && (!highValid || lowAbsError <= highAbsError)) {
        bestValid = true;
        bestPwmEq = lowPwmEq;
        bestAvgRPM = lowAvgRPM;
        bestAbsError = lowAbsError;
      } else if (highValid) {
        bestValid = true;
        bestPwmEq = highPwmEq;
        bestAvgRPM = highAvgRPM;
        bestAbsError = highAbsError;
      }
    }

    lockPwmEq = bestValid ? bestPwmEq : pwmNowEq;
    controlMode = MODE_LOCK;
    motorApplyForward(lockPwmEq);
    return;
  }

  float seekStepEq = getCandidateSeekStepEq(avgRPM);
  float nextPwm = pwmNowEq + ((float)seekDirection * seekStepEq);
  nextPwm = constrain(nextPwm, 0.0f, PWM_LIMIT_EQ);

  Serial.print("# SEEK_STEP_SELECTED ABS_ERR=");
  Serial.print(fabsf((float)targetRPM - avgRPM), 1);
  Serial.print(" STEP_EQ=");
  Serial.println(seekStepEq, 2);

  if (fabsf(nextPwm - pwmNowEq) < 0.001f) {
    Serial.println("# SEEK_PWM_LIMIT_REACHED_LOCK_BEST_AVAILABLE");
    lockPwmEq = bestValid ? bestPwmEq : pwmNowEq;
    controlMode = MODE_LOCK;
    motorApplyForward(lockPwmEq);
    return;
  }

  setPWM(nextPwm);
  seekStepCount++;
  startSeekHold();
}


// ============================================================
// RPM control
// ============================================================

void resetPrecisionLockState() {
  precisionBestValid = false;
  precisionBestPwmEq = 0.0f;
  precisionBestAvgRPM = 0.0f;
  precisionBestAbsError = 999999.0f;

  precisionLowValid = false;
  precisionLowPwmEq = 0.0f;
  precisionLowAvgRPM = 0.0f;
  precisionLowAbsError = 999999.0f;

  precisionHighValid = false;
  precisionHighPwmEq = 0.0f;
  precisionHighAvgRPM = 0.0f;
  precisionHighAbsError = 999999.0f;

  precisionEvalCount = 0;
  precisionNoImproveCount = 0;
  precisionInterpolationTried = false;
}

float getBlindStartSoftCeilingEq() {
  if (targetRPM <= 0) {
    return 0.0f;
  }

  float softCeiling = 18.0f + ((float)targetRPM * 0.055f);
  softCeiling = constrain(softCeiling, 28.0f, PWM_LIMIT_EQ);
  return softCeiling;
}

void updatePrecisionBest(float pwmEq, float avgRPM) {
  float signedError = (float)targetRPM - avgRPM;
  float absError = fabsf(signedError);

  precisionEvalCount++;

  if (signedError > 0.0f) {
    if (!precisionLowValid || absError < precisionLowAbsError) {
      precisionLowValid = true;
      precisionLowPwmEq = pwmEq;
      precisionLowAvgRPM = avgRPM;
      precisionLowAbsError = absError;
    }
  } else if (signedError < 0.0f) {
    if (!precisionHighValid || absError < precisionHighAbsError) {
      precisionHighValid = true;
      precisionHighPwmEq = pwmEq;
      precisionHighAvgRPM = avgRPM;
      precisionHighAbsError = absError;
    }
  } else {
    precisionLowValid = true;
    precisionHighValid = true;
    precisionLowPwmEq = pwmEq;
    precisionHighPwmEq = pwmEq;
    precisionLowAvgRPM = avgRPM;
    precisionHighAvgRPM = avgRPM;
    precisionLowAbsError = 0.0f;
    precisionHighAbsError = 0.0f;
  }

  if (!precisionBestValid || absError + PRECISION_IMPROVE_MARGIN_RPM < precisionBestAbsError) {
    precisionBestValid = true;
    precisionBestPwmEq = pwmEq;
    precisionBestAvgRPM = avgRPM;
    precisionBestAbsError = absError;
    precisionNoImproveCount = 0;

    Serial.print("# PRECISION_BEST_UPDATED PWM_EQ=");
    Serial.print(precisionBestPwmEq, 2);
    Serial.print(" AVG_RPM=");
    Serial.print(precisionBestAvgRPM, 1);
    Serial.print(" ERR=");
    Serial.println(precisionBestAbsError, 2);
  } else {
    precisionNoImproveCount++;

    Serial.print("# PRECISION_NO_IMPROVE COUNT=");
    Serial.print(precisionNoImproveCount);
    Serial.print(" CURRENT_PWM=");
    Serial.print(pwmEq, 2);
    Serial.print(" CURRENT_AVG_RPM=");
    Serial.print(avgRPM, 1);
    Serial.print(" CURRENT_ERR=");
    Serial.print(absError, 2);
    Serial.print(" BEST_PWM=");
    Serial.print(precisionBestPwmEq, 2);
    Serial.print(" BEST_ERR=");
    Serial.println(precisionBestAbsError, 2);
  }
}

float getPrecisionStepEq(float absError) {
  if (absError > PRECISION_COARSE_ERROR_RPM) {
    return PRECISION_COARSE_STEP_EQ;
  }

  if (absError > PRECISION_MID_ERROR_RPM) {
    return PRECISION_MID_STEP_EQ;
  }

  return PRECISION_FINE_STEP_EQ;
}

float estimatePrecisionInterpolatedPwm() {
  if (!precisionLowValid || !precisionHighValid) {
    return precisionBestValid ? precisionBestPwmEq : pwmNowEq;
  }

  float rpmSpan = precisionHighAvgRPM - precisionLowAvgRPM;
  if (fabsf(rpmSpan) < 0.001f) {
    return precisionBestValid ? precisionBestPwmEq : pwmNowEq;
  }

  float ratio = ((float)targetRPM - precisionLowAvgRPM) / rpmSpan;
  ratio = constrain(ratio, 0.0f, 1.0f);

  float est = precisionLowPwmEq + (precisionHighPwmEq - precisionLowPwmEq) * ratio;
  est = constrain(est, min(precisionLowPwmEq, precisionHighPwmEq), max(precisionLowPwmEq, precisionHighPwmEq));
  est = constrain(est, 0.0f, PWM_LIMIT_EQ);
  return est;
}

void lockToPrecisionBest(const char* reason) {
  if (!precisionBestValid) {
    precisionBestValid = true;
    precisionBestPwmEq = pwmNowEq;
    precisionBestAvgRPM = currentRPM;
    precisionBestAbsError = fabsf((float)targetRPM - currentRPM);
  }

  lockPwmEq = precisionBestPwmEq;
  controlMode = MODE_LOCK;
  motorApplyForward(lockPwmEq);

  Serial.print("# PRECISION_LOCK REASON=");
  Serial.print(reason);
  Serial.print(" LOCK_PWM_EQ=");
  Serial.print(lockPwmEq, 2);
  Serial.print(" BEST_AVG_RPM=");
  Serial.print(precisionBestAvgRPM, 1);
  Serial.print(" BEST_ERR=");
  Serial.println(precisionBestAbsError, 2);
}

void startPrecisionEvaluate() {
  resetMeasurementAverage();
  resetRPMBuffer();
  controlMode = MODE_TARGET_RAMP;

  Serial.print("# PRECISION_EVALUATE_START PWM_EQ=");
  Serial.print(pwmNowEq, 2);
  Serial.print(" TARGET=");
  Serial.println(targetRPM);
}

void setTargetRPM(int rpmInput) {
  if (rpmInput <= 0) {
    beginSoftStop();
    return;
  }

  if (rpmInput > 5000) {
    rpmInput = 5000;
  }

  bool wasCompletelyOff = (!motorEnabled && !softStopping && pwmNowEq <= 0.0f);

  targetRPM = rpmInput;
  motorEnabled = true;
  softStopping = false;

  resetCandidateState();

  if (wasCompletelyOff) {
    controlMode = MODE_ACCEL;
  } else {
    controlMode = MODE_TARGET_RAMP;
    resetMeasurementAverage();
  }

  digitalWrite(PIN_REN, HIGH);
  digitalWrite(PIN_LEN, HIGH);

  if (wasCompletelyOff) {
    pwmNowEq = 0.0f;
    lockPwmEq = 0.0f;
    resetRPMBuffer();
    motorApplyForward(0.0f);

    Serial.print("# TARGET_RPM_SET_FROM_STOP=");
    Serial.println(targetRPM);
  } else {
    motorApplyForward(pwmNowEq);

    Serial.print("# TARGET_RPM_CHANGED_KEEP_PWM TARGET=");
    Serial.print(targetRPM);
    Serial.print(" PWM_EQ=");
    Serial.println(pwmNowEq, 2);
  }

  lastPwmChangeMs = 0;

  Serial.println("# RPM_CONTROL_STARTED");
  Serial.println("# DATA_COLLECTION_NOT_STARTED_YET");
  Serial.println("# USE_MEASURE_COMMAND_AFTER_LOCK: m 0, m 1, m 2, m 3");
}

void controlRPM() {
  if (softStopping) {
    return;
  }

  unsigned long now = millis();

  if (now - lastControlMs < CONTROL_INTERVAL_MS) {
    return;
  }

  lastControlMs = now;

  if (!motorEnabled || targetRPM <= 0) {
    return;
  }

  float currentA = readCurrentA();
  float absCurrentA = fabsf(currentA);

  float stableRPM = 0.0f;
  bool stableRpmValid = getControlStableRPM(stableRPM);

  if (controlMode == MODE_ACCEL || controlMode == MODE_TARGET_RAMP || controlMode == MODE_TRACK) {
    if (absCurrentA > CURRENT_STRONG_DOWN_A) {
      if (canChangePWM()) {
        setPWM(pwmNowEq - PWM_CURRENT_STRONG_DOWN_STEP_EQ);
      }
      Serial.println("# CURRENT_OVER_20A_PWM_DOWN");
      return;
    }

    if (absCurrentA >= CURRENT_SLOWDOWN_A) {
      if (canChangePWM()) {
        setPWM(pwmNowEq - PWM_CURRENT_DOWN_STEP_EQ);
      }
      Serial.println("# CURRENT_HIGH_PWM_DOWN");
      return;
    }
  }

  if (controlMode == MODE_ACCEL) {
    if (!stableRpmValid) {
      float softCeiling = getBlindStartSoftCeilingEq();
      float nextPwm = pwmNowEq;

      if (pwmNowEq < softCeiling) {
        nextPwm = pwmNowEq + 2.00f;
      } else {
        nextPwm = pwmNowEq + 0.50f;
      }

      nextPwm = constrain(nextPwm, 0.0f, PWM_LIMIT_EQ);
      setPWM(nextPwm);

      Serial.print("# ACCEL_WAIT_FIRST_VALID_RPM PWM_EQ=");
      Serial.print(pwmNowEq, 2);
      Serial.print(" SOFT_CEILING=");
      Serial.println(softCeiling, 2);
      return;
    }

    float error = (float)targetRPM - stableRPM;
    float absError = fabsf(error);

    if (absError <= PRECISION_ENTRY_ERROR_RPM) {
      Serial.print("# ENTER_PRECISION_FROM_ACCEL STABLE_RPM=");
      Serial.print(stableRPM, 1);
      Serial.print(" TARGET=");
      Serial.print(targetRPM);
      Serial.print(" ERR=");
      Serial.println(error, 1);
      startPrecisionEvaluate();
      return;
    }

    float stepEq = getPrecisionStepEq(absError);
    float nextPwm = pwmNowEq;

    if (error > 0.0f) {
      nextPwm = pwmNowEq + stepEq;
    } else {
      nextPwm = pwmNowEq - stepEq;
    }

    nextPwm = constrain(nextPwm, 0.0f, PWM_LIMIT_EQ);
    setPWM(nextPwm);

    Serial.print("# ACCEL_CONVERGE STABLE_RPM=");
    Serial.print(stableRPM, 1);
    Serial.print(" TARGET=");
    Serial.print(targetRPM);
    Serial.print(" ERR=");
    Serial.print(error, 1);
    Serial.print(" STEP_EQ=");
    Serial.print(stepEq, 2);
    Serial.print(" PWM_EQ=");
    Serial.println(pwmNowEq, 2);
    return;
  }

  if (controlMode == MODE_TRACK || controlMode == MODE_SEEK_HOLD || controlMode == MODE_CANDIDATE_HOLD) {
    startPrecisionEvaluate();
    return;
  }

  if (controlMode == MODE_TARGET_RAMP) {
    motorApplyForward(pwmNowEq);

    unsigned long elapsed = now - measureStartMs;
    addMeasurementSample(elapsed, PRECISION_IGNORE_MS, PRECISION_HOLD_MS);

    if (elapsed < PRECISION_HOLD_MS) {
      return;
    }

    if (measureRpmCount < PRECISION_MIN_SAMPLES) {
      return;
    }

    float avgRPM = getMeasurementAverage();

    if (avgRPM < CONTROL_RPM_MIN_VALID_VALUE) {
      Serial.println("# PRECISION_EVALUATE_SKIP_INVALID_RPM_ZERO_OR_DROPOUT");
      resetMeasurementAverage();
      resetRPMBuffer();
      return;
    }

    float signedError = (float)targetRPM - avgRPM;
    float absError = fabsf(signedError);

    Serial.print("# PRECISION_EVALUATE PWM_EQ=");
    Serial.print(pwmNowEq, 2);
    Serial.print(" AVG_RPM=");
    Serial.print(avgRPM, 1);
    Serial.print(" ERR=");
    Serial.print(signedError, 2);
    Serial.print(" SAMPLES=");
    Serial.println(measureRpmCount);

    updatePrecisionBest(pwmNowEq, avgRPM);

    if (precisionBestAbsError <= PRECISION_EXCELLENT_ERROR_RPM && precisionEvalCount >= PRECISION_MIN_EVAL_BEFORE_LOCK) {
      lockToPrecisionBest("excellent_error_after_local_check");
      return;
    }

    if (precisionLowValid && precisionHighValid && !precisionInterpolationTried) {
      float interpolatedPwm = estimatePrecisionInterpolatedPwm();
      precisionInterpolationTried = true;

      if (fabsf(interpolatedPwm - pwmNowEq) >= 0.001f) {
        Serial.print("# PRECISION_INTERPOLATED_TEST PWM_EQ=");
        Serial.println(interpolatedPwm, 2);
        setPWM(interpolatedPwm);
        startPrecisionEvaluate();
        return;
      }
    }

    if (precisionEvalCount >= PRECISION_MAX_EVAL_COUNT) {
      lockToPrecisionBest("max_eval_best_error");
      return;
    }

    if (precisionEvalCount >= PRECISION_MIN_EVAL_BEFORE_LOCK && precisionNoImproveCount >= PRECISION_NO_IMPROVE_LIMIT) {
      lockToPrecisionBest("no_more_improvement_best_error");
      return;
    }

    float stepEq = getPrecisionStepEq(absError);
    float nextPwm = pwmNowEq;

    if (signedError > 0.0f) {
      nextPwm = pwmNowEq + stepEq;
    } else if (signedError < 0.0f) {
      nextPwm = pwmNowEq - stepEq;
    } else {
      lockToPrecisionBest("exact_average_error_zero");
      return;
    }

    nextPwm = constrain(nextPwm, 0.0f, PWM_LIMIT_EQ);

    if (fabsf(nextPwm - pwmNowEq) < 0.001f) {
      lockToPrecisionBest("pwm_limit_best_error");
      return;
    }

    Serial.print("# PRECISION_NEXT_PWM CURRENT_ERR=");
    Serial.print(absError, 2);
    Serial.print(" STEP_EQ=");
    Serial.print(stepEq, 2);
    Serial.print(" NEXT_PWM_EQ=");
    Serial.println(nextPwm, 2);

    setPWM(nextPwm);
    startPrecisionEvaluate();
    return;
  }

  if (controlMode == MODE_LOCK) {
    motorApplyForward(lockPwmEq);
    return;
  }

  motorApplyForward(pwmNowEq);
}


// ============================================================
// Labels / data capture
// ============================================================

void resetConditionLabel() {
  conditionNumber = -1;
  strcpy(stateLabel, "normal");
  strcpy(faultTypeLabel, "none");
}

bool setConditionLabel(int condition) {
  conditionNumber = condition;

  if (condition == 0) {
    strcpy(stateLabel, "normal");
    strcpy(faultTypeLabel, "none");
    return true;
  }

  if (condition == 1) {
    strcpy(stateLabel, "fault");
    strcpy(faultTypeLabel, "unbalance");
    return true;
  }

  if (condition == 2) {
    strcpy(stateLabel, "fault");
    strcpy(faultTypeLabel, "misalignment");
    return true;
  }

  if (condition == 3) {
    strcpy(stateLabel, "fault");
    strcpy(faultTypeLabel, "looseness");
    return true;
  }

  return false;
}

void armMeasurement(int condition) {
  if (!setConditionLabel(condition)) {
    Serial.println("# MEASUREMENT_ARM_ERROR_INVALID_CONDITION");
    Serial.println("# use m 0 normal, m 1 unbalance, m 2 misalignment, m 3 looseness");
    return;
  }

  if (targetRPM <= 0 || !motorEnabled) {
    Serial.println("# MEASUREMENT_ARM_ERROR_TARGET_RPM_NOT_SET");
    Serial.println("# input target rpm first, example: 500");
    return;
  }

  dataMode = DATA_MEASUREMENT_ARMED;
  armedLockStartMs = 0;
  csvHeaderPrintedMeasurement = false;

  Serial.print("# MEASUREMENT_ARMED CONDITION=");
  Serial.print(conditionNumber);
  Serial.print(",");
  Serial.print(stateLabel);
  Serial.print(",");
  Serial.println(faultTypeLabel);
  Serial.println("# WAITING_FOR_LOCK_AND_STABLE_RPM");
}

void cancelMeasurement() {
  if (dataMode == DATA_MEASUREMENT_ARMED || dataMode == DATA_MEASURING) {
    Serial.println("# MEASUREMENT_CANCELLED");
  }

  dataMode = DATA_IDLE;
  resetConditionLabel();
  sampleIndex = 0;
  csvHeaderPrintedMeasurement = false;
}

void startMeasurementNow() {
  dataMode = DATA_MEASURING;
  dataStartMs = millis();
  previousSampleMs = dataStartMs;
  sampleIndex = 0;
  csvHeaderPrintedMeasurement = false;

  Serial.print("# MEASUREMENT_STARTED_AFTER_LOCK TARGET_RPM=");
  Serial.print(targetRPM);
  Serial.print(" CONDITION=");
  Serial.print(conditionNumber);
  Serial.print(",");
  Serial.print(stateLabel);
  Serial.print(",");
  Serial.println(faultTypeLabel);

  printMeasurementHeader();
}

void stopMeasurementFinished() {
  Serial.println("# MEASUREMENT_END");
  dataMode = DATA_IDLE;
  resetConditionLabel();
  sampleIndex = 0;
  csvHeaderPrintedMeasurement = false;
}

void startRealtimeStream() {
  dataMode = DATA_REALTIME_STREAM;
  dataStartMs = millis();
  previousSampleMs = dataStartMs;
  sampleIndex = 0;
  csvHeaderPrintedRealtime = false;

  Serial.println("# REALTIME_STREAM_STARTED");
  printRealtimeHeader();
}

void stopRealtimeStream() {
  if (dataMode == DATA_REALTIME_STREAM) {
    Serial.println("# REALTIME_STREAM_STOPPED");
  }

  dataMode = DATA_IDLE;
  sampleIndex = 0;
  csvHeaderPrintedRealtime = false;
}

void handleMeasurementArmed() {
  if (dataMode != DATA_MEASUREMENT_ARMED) {
    return;
  }

  if (controlMode != MODE_LOCK) {
    armedLockStartMs = 0;
    return;
  }

  float rpmError = fabsf((float)targetRPM - currentRPM);

  if (rpmError > MEASUREMENT_MAX_RPM_ERROR) {
    armedLockStartMs = 0;
    return;
  }

  unsigned long now = millis();

  if (armedLockStartMs == 0) {
    armedLockStartMs = now;
    Serial.println("# LOCK_DETECTED_MEASUREMENT_SETTLE_TIMER_STARTED");
    return;
  }

  if (now - armedLockStartMs >= MEASUREMENT_LOCK_SETTLE_MS) {
    startMeasurementNow();
  }
}

void printMeasurementHeader() {
  if (csvHeaderPrintedMeasurement) {
    return;
  }

  sendCsvLine("sample_index,time_ms,elapsed_ms,ax_g,ay_g,az_g,total_g,rpm,target_rpm,rpm_error,pwm_eq,duty_10bit,acs_v,current_a,control_mode,state,fault_type");
  csvHeaderPrintedMeasurement = true;
}

void printRealtimeHeader() {
  if (csvHeaderPrintedRealtime) {
    return;
  }

  sendCsvLine("sample_index,time_ms,elapsed_ms,ax_g,ay_g,az_g,total_g,rpm,target_rpm,rpm_error,pwm_eq,duty_10bit,acs_v,current_a,control_mode");
  csvHeaderPrintedRealtime = true;
}

void printCsvRow(bool withLabel) {
  int16_t xRaw = 0;
  int16_t yRaw = 0;
  int16_t zRaw = 0;

  bool ok = readAccelRaw(xRaw, yRaw, zRaw);
  if (!ok) {
    sendLineBoth("# ADXL345_READ_ERROR");
    return;
  }

  unsigned long now = millis();
  unsigned long elapsedMs = now - dataStartMs;

  float ax_g = xRaw * ADXL345_SCALE_G_PER_LSB;
  float ay_g = yRaw * ADXL345_SCALE_G_PER_LSB;
  float az_g = zRaw * ADXL345_SCALE_G_PER_LSB;
  float total_g = sqrtf(ax_g * ax_g + ay_g * ay_g + az_g * az_g);

  float rpm = currentRPM;
  float rpmError = (float)targetRPM - rpm;

  int duty10 = pwmEqToDuty10Bit(pwmNowEq);
  float acsV = readAcsVoltage();
  float currentA = (acsV - ACS_ZERO_VOLTAGE) / ACS_SENSITIVITY;

  String line;
  line.reserve(220);

  line += String(sampleIndex);
  line += ",";
  line += String(now);
  line += ",";
  line += String(elapsedMs);
  line += ",";
  line += String(ax_g, 5);
  line += ",";
  line += String(ay_g, 5);
  line += ",";
  line += String(az_g, 5);
  line += ",";
  line += String(total_g, 5);
  line += ",";
  line += String(rpm, 2);
  line += ",";
  line += String(targetRPM);
  line += ",";
  line += String(rpmError, 2);
  line += ",";
  line += String(pwmNowEq, 2);
  line += ",";
  line += String(duty10);
  line += ",";
  line += String(acsV, 4);
  line += ",";
  line += String(currentA, 4);
  line += ",";
  line += String(modeName(controlMode));

  if (withLabel) {
    line += ",";
    line += String(stateLabel);
    line += ",";
    line += String(faultTypeLabel);
  }

  queueCloudTelemetry(sampleIndex, now, ax_g, ay_g, az_g, total_g, rpm, targetRPM, rpmError, pwmNowEq, duty10, acsV, currentA, modeName(controlMode));
  if (withLabel || PRINT_REALTIME_CSV_TO_SERIAL) {
    sendCsvLine(line);
  }
  sampleIndex++;
}

void handleDataOutput() {
  handleMeasurementArmed();

  // v1.4: physical telemetry is independent from target RPM and motor state.
  // The dashboard can start monitoring immediately at RPM=0. AI gating is done server-side.
  const bool measurementActive = (dataMode == DATA_MEASURING);
  const bool realtimeActive = (dataMode == DATA_REALTIME_STREAM);
  if (!CLOUD_TELEMETRY_ALWAYS_ON && !measurementActive && !realtimeActive) {
    return;
  }

  unsigned long now = millis();
  if (now - previousSampleMs < SAMPLE_INTERVAL_MS) {
    return;
  }
  previousSampleMs = now;

  if (measurementActive) {
    unsigned long elapsed = now - dataStartMs;
    if (elapsed >= MEASUREMENT_DURATION_MS) {
      stopMeasurementFinished();
      return;
    }
    printCsvRow(true);
    return;
  }

  // DATA_IDLE / DATA_MEASUREMENT_ARMED / DATA_REALTIME_STREAM all keep cloud telemetry alive.
  printCsvRow(false);
}


// ============================================================
// Input handling
// ============================================================

bool parseManualPWMCommand(String cmd, float &manualPwmEq) {
  String s = cmd;
  s.trim();
  s.toLowerCase();

  if (s.startsWith("pwm=")) {
    s = s.substring(4);
  } else if (s.startsWith("pwm ")) {
    s = s.substring(4);
  } else if (s.startsWith("p=")) {
    s = s.substring(2);
  } else if (s.startsWith("p ")) {
    s = s.substring(2);
  } else {
    return false;
  }

  s.trim();
  if (s.length() == 0) {
    return false;
  }

  manualPwmEq = s.toFloat();
  return true;
}

bool parseMeasureCommand(String cmd, int &condition) {
  String s = cmd;
  s.trim();
  s.toLowerCase();

  if (s.startsWith("m ")) {
    s = s.substring(2);
  } else if (s.startsWith("measure ")) {
    s = s.substring(8);
  } else if (s.startsWith("collect ")) {
    s = s.substring(8);
  } else {
    return false;
  }

  s.trim();

  if (s == "normal") {
    condition = 0;
    return true;
  }
  if (s == "unbalance") {
    condition = 1;
    return true;
  }
  if (s == "misalignment") {
    condition = 2;
    return true;
  }
  if (s == "looseness") {
    condition = 3;
    return true;
  }

  int v = s.toInt();
  if (v >= 0 && v <= 3) {
    condition = v;
    return true;
  }

  return false;
}

bool parseTargetRPMCommand(String cmd, int &rpmValue) {
  String s = cmd;
  s.trim();
  s.toLowerCase();

  if (s.startsWith("rpm=")) {
    s = s.substring(4);
  } else if (s.startsWith("rpm ")) {
    s = s.substring(4);
  } else if (s.startsWith("target=")) {
    s = s.substring(7);
  } else if (s.startsWith("target ")) {
    s = s.substring(7);
  }

  s.trim();
  if (s.length() == 0) {
    return false;
  }

  bool hasDigit = false;
  for (unsigned int i = 0; i < s.length(); i++) {
    char c = s.charAt(i);
    if (isDigit(c)) {
      hasDigit = true;
    } else if (!(c == '+' || c == '-' || c == ' ')) {
      return false;
    }
  }

  if (!hasDigit) {
    return false;
  }

  rpmValue = s.toInt();
  return true;
}

void handleCommand(String cmd) {
  cmd.trim();
  if (cmd.length() == 0) {
    return;
  }

  String lower = cmd;
  lower.toLowerCase();

  if (lower == "help" || lower == "?") {
    printHelp();
    return;
  }

  if (lower == "status") {
    printStatusLine();
    publishControlStatus("local_status");
    return;
  }

  if (lower == "wifi setup") {
    requestWiFiSetupPortal();
    return;
  }

  if (lower == "wifi list") {
    loadSavedWiFi();
    printSavedWiFi();
    return;
  }

  if (lower == "wifi clear") {
    savedWiFiCount = 0;
    persistSavedWiFi();
    Serial.println("# WIFI_SAVED_NETWORKS_CLEARED");
    requestWiFiSetupPortal();
    return;
  }

  if (lower == "remote on") {
    remoteControlEnabled = true;
    Serial.println("# REMOTE_CONTROL_LOCAL_ARM_ON");
    publishControlStatus("local_arm_on");
    return;
  }

  if (lower == "remote off") {
    remoteControlEnabled = false;
    remoteControlActive = false;
    beginSoftStop();
    Serial.println("# REMOTE_CONTROL_LOCAL_ARM_OFF_AND_STOP");
    publishControlStatus("local_arm_off");
    return;
  }

  if (lower == "stop" || lower == "x" || lower == "0") {
    remoteControlActive = false;
    beginSoftStop();
    publishControlStatus("local_stop");
    return;
  }

  if (lower == "hardoff" || lower == "off") {
    remoteControlActive = false;
    motorHardOff();
    Serial.println("# MOTOR_HARD_OFF");
    return;
  }

  if (lower == "reset") {
    Serial.println("# RESET_REQUESTED_SOFT_STOP");
    beginSoftStop();
    return;
  }

  if (lower == "r" || lower == "stream" || lower == "realtime" || lower == "run") {
    startRealtimeStream();
    return;
  }

  if (lower == "r off" || lower == "stream off" || lower == "realtime off") {
    stopRealtimeStream();
    return;
  }

  if (lower == "cancel" || lower == "m off" || lower == "measure off") {
    cancelMeasurement();
    return;
  }

  float manualPwmEq = 0.0f;
  if (parseManualPWMCommand(cmd, manualPwmEq)) {
    remoteControlActive = false;
    targetRPM = 0;
    motorEnabled = true;
    softStopping = false;
    controlMode = MODE_IDLE;
    resetCandidateState();
    motorApplyForward(manualPwmEq);

    Serial.print("# MANUAL_PWM_SET PWM_EQ=");
    Serial.print(pwmNowEq, 2);
    Serial.print(" DUTY_10BIT=");
    Serial.print(pwmEqToDuty10Bit(pwmNowEq));
    Serial.print("/");
    Serial.println(PWM_DUTY_MAX);
    return;
  }

  int condition = -1;
  if (parseMeasureCommand(cmd, condition)) {
    armMeasurement(condition);
    return;
  }

  int rpmValue = 0;
  if (parseTargetRPMCommand(cmd, rpmValue)) {
    remoteControlActive = false;
    if (rpmValue > 0) {
      setTargetRPM(rpmValue);
    } else {
      beginSoftStop();
    }
    return;
  }

  Serial.println("# INPUT_ERROR");
  printHelp();
}

void readSerialInput() {
  while (Serial.available() > 0) {
    char c = Serial.read();

    if (c == '\n' || c == '\r') {
      if (inputLine.length() > 0) {
        handleCommand(inputLine);
        inputLine = "";
      }
    } else {
      inputLine += c;
    }
  }
}


// ============================================================
// Help / status output
// ============================================================

void printBootMessage() {
  sendLineBoth("# ESP32_INTEGRATED_RPM_FAULT_DETECTION_READY");
  sendLineBoth("# Hardware: ESP32 + BTS7960 + Hall + ADXL345 + ACS712_30A");
  sendLineBoth("# Cloud: AWS MQTT TLS telemetry always-on + remote target RPM control");
  sendLineBoth("# Data collection excludes acceleration/seek/candidate intervals");
  sendLineBoth("# Measurement starts only after LOCK and stable RPM");
  sendLineBoth("# Fast precision RPM lock enabled for every target RPM");
  sendLineBoth("# LOCK uses the best measured average-RPM error, not the first acceptable band");
  sendLineBoth("# After LOCK, PWM is fixed and not adjusted again");
  sendLineBoth("# RPM dropout and single spike values are ignored for control decision");
  printHelp();
}

void printHelp() {
  sendLineBoth("# COMMANDS");
  sendLineBoth("# 500                : set target RPM 500 and start RPM control");
  sendLineBoth("# rpm 500            : same as above");
  sendLineBoth("# target 500         : same as above");
  sendLineBoth("# m 0                : arm measurement normal");
  sendLineBoth("# m 1                : arm measurement unbalance");
  sendLineBoth("# m 2                : arm measurement misalignment");
  sendLineBoth("# m 3                : arm measurement looseness");
  sendLineBoth("# r                  : start realtime CSV stream");
  sendLineBoth("# r off              : stop realtime CSV stream");
  sendLineBoth("# pwm 55.5           : manual PWM_EQ output");
  sendLineBoth("# stop or x or 0     : soft stop motor");
  sendLineBoth("# hardoff            : immediate motor off");
  sendLineBoth("# status             : print current status");
  sendLineBoth("# wifi setup         : open NEXis Wi-Fi setup portal");
  sendLineBoth("# wifi list          : list saved Wi-Fi SSIDs/priorities");
  sendLineBoth("# wifi clear         : delete saved Wi-Fi and open setup portal");
  sendLineBoth("# remote on          : re-enable AWS remote RPM commands (enabled automatically at boot)");
  sendLineBoth("# remote off         : manually disable AWS remote control and soft stop");
  sendLineBoth("# help               : print this help");
}

void printStatusLine() {
  float acsV = readAcsVoltage();
  float currentA = (acsV - ACS_ZERO_VOLTAGE) / ACS_SENSITIVITY;
  int duty10 = pwmEqToDuty10Bit(pwmNowEq);
  float rpmError = (float)targetRPM - currentRPM;

  String line;
  line.reserve(260);

  line += "# STATUS TARGET=";
  line += String(targetRPM);
  line += " RPM=";
  line += String(currentRPM, 1);
  line += " ERR=";
  line += String(rpmError, 1);
  line += " PWM_EQ=";
  line += String(pwmNowEq, 2);
  line += " DUTY_10BIT=";
  line += String(duty10);
  line += "/";
  line += String(PWM_DUTY_MAX);
  line += " ACS_V=";
  line += String(acsV, 3);
  line += " CURRENT_A=";
  line += String(currentA, 3);
  line += " CONTROL_MODE=";
  line += String(modeName(controlMode));
  line += " DATA_MODE=";
  line += String(dataModeName(dataMode));
  line += " MOTOR=";
  line += motorEnabled ? "ON" : "OFF";

  sendLineBoth(line);
}


// ============================================================
// setup / loop
// ============================================================

void setup() {
  Serial.begin(SERIAL_BAUDRATE);
  delay(1000);

  pinMode(PIN_HALL, INPUT_PULLUP);
  pinMode(PIN_REN, OUTPUT);
  pinMode(PIN_LEN, OUTPUT);

  digitalWrite(PIN_REN, LOW);
  digitalWrite(PIN_LEN, LOW);

  Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL);
  delay(100);

  bool adxlOk = setupADXL345();
  if (!adxlOk) {
    Serial.println("# WARNING_ADXL345_NOT_READY_CHECK_WIRING_SDA_SCL_VCC_GND");
  }

  setupWiFiClient();

  analogReadResolution(12);
  analogSetPinAttenuation(PIN_ACS, ADC_11db);

  setupPWM();
  writeRPWM(0);
  writeLPWM(0);

  attachInterrupt(digitalPinToInterrupt(PIN_HALL), hallISR, FALLING);

  resetRPMBuffer();
  resetCandidateState();
  resetConditionLabel();

  lastControlMs = millis();
  lastPwmChangeMs = 0;
  lastStatusMs = millis();
  previousSampleMs = millis();
  dataStartMs = previousSampleMs;

  printBootMessage();
  Serial.println("# CLOUD_TELEMETRY_ALWAYS_ON RPM_INPUT_NOT_REQUIRED");
  Serial.println("# REMOTE_CONTROL_AUTO_ENABLED_SERVER_ARM_REQUIRED");
}

void loop() {
  serviceWiFiSetupPortal();
  updateRPM();
  maintainTcpConnection();
  readSerialInput();
  readTcpInput();
  handleCloudFailSafe();
  handleSoftStop();
  controlRPM();
  handleDataOutput();

  if (dataMode == DATA_IDLE || dataMode == DATA_MEASUREMENT_ARMED) {
    unsigned long now = millis();
    if (now - lastStatusMs >= LIVE_STATUS_INTERVAL_MS) {
      lastStatusMs = now;
      printStatusLine();
    }
  }
}