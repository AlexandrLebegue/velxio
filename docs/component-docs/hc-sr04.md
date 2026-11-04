# HC-SR04 (hc-sr04)
Status: complete
Wokwi tag: wokwi-hc-sr04

## Pins
| pin | role | typical connection |
|---|---|---|
| VCC | Power supply (5V) | 5V from the board |
| TRIG | Starts a measurement (pulse >= 10 us) | Any digital output (e.g. 3) |
| ECHO | High pulse whose length encodes the distance | Any digital input (e.g. 2) |
| GND | Ground | GND |

## Attributes
| attribute | type | default | role |
|---|---|---|---|
| distance | number | 400 | Initial distance in centimeters (2-400 range) |

## Wiring
- Arduino Uno: VCC -> 5V, GND -> GND, TRIG -> pin 3, ECHO -> pin 2
- ESP32: VCC -> 3V3, GND -> GND, TRIG -> GPIO 13, ECHO -> GPIO 14

## Minimal sketch
Not compiled.
```cpp
// HC-SR04: read the distance once per second on the serial port
const int PIN_TRIG = 3;
const int PIN_ECHO = 2;

void setup() {
  Serial.begin(115200);
  pinMode(PIN_TRIG, OUTPUT);
  pinMode(PIN_ECHO, INPUT);
  digitalWrite(PIN_TRIG, LOW);
}

void loop() {
  // A pulse of 10 us or longer on TRIG starts a measurement
  digitalWrite(PIN_TRIG, HIGH);
  delayMicroseconds(10);
  digitalWrite(PIN_TRIG, LOW);
  // ECHO stays high proportionally to distance; cm = us / 58
  long duration = pulseIn(PIN_ECHO, HIGH, 30000);
  Serial.print("Distance (cm): ");
  Serial.println(duration / 58);
  delay(1000);
}
```

## Pitfalls
- The TRIG pulse must last 10 us or more; shorter pulses do not start a measurement.
- Always give pulseIn() a timeout: with no target in range ECHO may never go high and the sketch would hang.
- The module is nominally 5V: the ECHO output is 5V, which is not safe for 3.3V GPIOs (ESP32) without a voltage divider on real hardware.
- cm = pulseMicros / 58 (inches = / 148); the simulated range is 2 to 400 cm.

## Sources
- https://docs.wokwi.com/parts/wokwi-hc-sr04: VCC/TRIG/ECHO/GND pins, distance attribute (default 400), TRIG 10 us protocol, us-to-cm/inch factors.
- frontend/src/data/examples.ts: Velxio wiring (VCC -> 5V/3.3V, GND, TRIG, ECHO).
