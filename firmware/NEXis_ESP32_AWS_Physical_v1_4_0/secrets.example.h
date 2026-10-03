#pragma once
#include <Arduino.h>

// Copy to secrets.h and replace the placeholders.
// Never commit secrets.h.
static const char* WIFI_SETUP_AP_PASSWORD = "CHANGE_ME_SETUP_AP_PASSWORD";
static const char* MQTT_HOST = "YOUR_SERVER_HOST_OR_IP";
static const uint16_t MQTT_PORT = 8883;
static const char* MQTT_USERNAME = "YOUR_MQTT_USERNAME";
static const char* MQTT_PASSWORD = "YOUR_MQTT_PASSWORD";
static const char* MQTT_TOPIC_PREFIX = "nexis/esp32/rotor_rig_01";

// Paste the CA certificate that signed the MQTT server certificate.
static const char MQTT_CA_CERT[] PROGMEM = R"EOF(
-----BEGIN CERTIFICATE-----
YOUR_CA_CERTIFICATE_HERE
-----END CERTIFICATE-----
)EOF";
