# Servo (servo)
Status: complete
Wokwi tag: wokwi-servo

## Pins
| pin | role | typical connection |
|---|---|---|
| PWM | Control signal | PWM-capable pin (e.g. 9 on the Uno) |
| V+ | Positive supply (5V) | 5V from the board or an external supply |
| GND | Ground | GND |

## Attributes
| attribute | type | default | role |
|---|---|---|---|
| angle | number | 0 | Current shaft angle, 0 to 180 degrees |
| horn | string | 'single' | Horn type: "single", "double" or "cross" |
| hornColor | string | '#ccc' | Horn color (hex) |

## Wiring
- Arduino Uno: PWM -> pin 9, V+ -> 5V, GND -> GND
- ESP32: PWM -> GPIO 13, V+ -> 5V, GND -> GND

## Minimal sketch
Not compiled.
```cpp
// Servo: continuous sweep 0 deg -> 180 deg -> 0 deg
#include <Servo.h>

Servo myServo;
const int PIN_SERVO = 9;

void setup() {
  myServo.attach(PIN_SERVO);
  myServo.write(0);
}

void loop() {
  for (int a = 0; a <= 180; a += 5) {
    myServo.write(a);
    delay(30);
  }
  for (int a = 180; a >= 0; a -= 5) {
    myServo.write(a);
    delay(30);
  }
}
```

## Pitfalls
- The Servo.h library (Arduino and ESP32 cores) is required: the signal is a 50 Hz PWM encoding the angle.
- Do not power servos from the 3V3 pin of the ESP32 (current-limited): use the 5V pin or an external supply for V+.
- The Uno 5V regulator under USB only provides ~500 mA: at most 2-3 servos without an external supply.
- In Wokwi the sweep is fixed at 0-180 deg with hard stops at both ends.

## Sources
- https://docs.wokwi.com/parts/wokwi-servo: PWM/V+/GND pins, 0-180 deg range, horn/hornColor attributes.
- Repo examples (frontend/src/data/examples.ts): Uno servo wired PWM/V+/GND.
