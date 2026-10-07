# Hardware wiring

This document summarizes the reference wiring used by the NEXis physical rotating-machine rig. The GPIO assignments below match `firmware/NEXis_ESP32_Physical/NEXis_ESP32_Physical.ino`.

## ESP32 pin map

| Function | Module / signal | ESP32 pin | Notes |
|---|---|---:|---|
| RPM feedback | Hall sensor output | GPIO 32 | Configured as `INPUT_PULLUP`; falling-edge interrupt |
| Motor current | ACS712 analog output | GPIO 36 | 12-bit ADC input |
| Motor drive | BTS7960 RPWM | GPIO 25 | PWM output |
| Motor drive | BTS7960 LPWM | GPIO 26 | PWM output |
| Motor drive enable | BTS7960 R_EN | GPIO 27 | Digital output |
| Motor drive enable | BTS7960 L_EN | GPIO 14 | Digital output |
| Vibration sensor | ADXL345 SDA | GPIO 21 | I2C data |
| Vibration sensor | ADXL345 SCL | GPIO 22 | I2C clock |

## Reference connections

### ADXL345

| ADXL345 | ESP32 |
|---|---|
| SDA | GPIO 21 |
| SCL | GPIO 22 |
| GND | GND |
| VCC | 3.3 V |

The firmware uses I2C address `0x53` and samples vibration at 100 Hz.

### Hall RPM sensor

| Hall sensor | ESP32 |
|---|---|
| Signal / OUT | GPIO 32 |
| GND | GND |
| Supply | Use the supply required by the installed sensor module |

The firmware uses the ESP32 pull-up and counts falling edges. The configured reference is one pulse per revolution.

### ACS712 30 A

| ACS712 | Connection |
|---|---|
| OUT | ESP32 GPIO 36 |
| GND | Common GND |
| IP+ / IP- | In series with the motor-current path |
| VCC | According to the ACS712 module specification |

The firmware uses a 12-bit ADC and the calibration constants stored in the firmware. Ensure the voltage presented to GPIO 36 stays within the ESP32 ADC input range.

### BTS7960 motor driver

| BTS7960 | ESP32 / power |
|---|---|
| RPWM | GPIO 25 |
| LPWM | GPIO 26 |
| R_EN | GPIO 27 |
| L_EN | GPIO 14 |
| Logic GND | ESP32 GND / common GND |
| Motor outputs | 775 DC motor |
| Motor supply | 12 V power supply used by the test rig |

Do not connect the 12 V motor supply directly to an ESP32 GPIO or 3.3 V rail. Keep the motor-power path separate from logic power while maintaining the required common reference ground for control signals.

## Signal path

```text
ADXL345 ----I2C----> ESP32
ACS712 -----ADC----> ESP32
Hall Sensor--IRQ---> ESP32
                       |
                       +---- RPWM / LPWM / EN ----> BTS7960 ----> 775 DC Motor
                       |
                       +---- MQTT/TLS ------------> NEXis Server
```

## Firmware source of truth

If the wiring is changed, update both this document and the pin definitions near the top of:

```text
firmware/NEXis_ESP32_Physical/NEXis_ESP32_Physical.ino
```

The current definitions are:

```cpp
#define PIN_HALL    32
#define PIN_ACS     36
#define PIN_RPWM    25
#define PIN_LPWM    26
#define PIN_REN     27
#define PIN_LEN     14
#define PIN_I2C_SDA 21
#define PIN_I2C_SCL 22
```
