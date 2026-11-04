# Analog Joystick (analog-joystick)
Status: complete
Wokwi tag: wokwi-analog-joystick

## Pins
| pin | role | typical connection |
|---|---|---|
| VCC | Positive power supply | 5V on Uno, 3V3 on ESP32 |
| VERT | Vertical axis output (analog, 0 bottom to VCC top) | A0 on Uno, GPIO 34 on ESP32 |
| HORZ | Horizontal axis output (analog, 0 right to VCC left) | A1 on Uno, GPIO 35 on ESP32 |
| SEL | Center push button (normally open) | Pin 2 with pull-up |
| GND | Ground | GND |

## Attributes
| attribute | type | default | role |
|---|---|---|---|
| bounce | string | '' | set to "0" to disable button contact bouncing |
| xValue | number | 0 | current horizontal axis value (x control) |
| yValue | number | 0 | current vertical axis value (y control) |
| pressed | boolean | False | state of the center push button (SEL) |

## Wiring
- Arduino Uno: VCC -> 5V, GND -> GND, VERT -> A0, HORZ -> A1, SEL -> pin 2
- ESP32: VCC -> 3V3, GND -> GND, VERT -> GPIO 34, HORZ -> GPIO 35, SEL -> GPIO 15

## Minimal sketch
Not compiled.
```cpp
// Analog joystick: read both axes and the center push button
#define VERT_PIN A0
#define HORZ_PIN A1
#define SEL_PIN 2

void setup() {
  Serial.begin(115200);
  pinMode(VERT_PIN, INPUT);
  pinMode(HORZ_PIN, INPUT);
  pinMode(SEL_PIN, INPUT_PULLUP);
}

void loop() {
  int v = analogRead(VERT_PIN);
  int h = analogRead(HORZ_PIN);
  bool pressed = digitalRead(SEL_PIN) == LOW;
  Serial.printf("vert %d  horz %d  pressed %d\n", v, h, pressed ? 1 : 0);
  delay(200);
}
```

## Pitfalls
- SEL is a switch to ground: use INPUT_PULLUP and treat LOW as pressed, otherwise the pin floats when released.
- The idle (centered) position sits at VCC/2 (about 512 at 5V): measure it at startup or use map(x, 0, 1023, -100, 100) for a signed axis.
- HORZ increases toward the left (0 = right, 1023 = left) and VERT increases upward, which is the opposite of what some gamepad APIs expect.
- The button bounces by default in the simulator; set the bounce attribute to "0" if your code polls it tightly.

## Sources
- https://docs.wokwi.com/parts/wokwi-analog-joystick: pins, VCC/2 idle voltage, SEL behavior, bounce attribute, Uno wiring table, position table.
- Repo examples (frontend/src/data/examples.ts): ESP32 wiring VCC -> 3V3, VERT -> GPIO 34, HORZ -> GPIO 35, SEL -> GPIO 15.
