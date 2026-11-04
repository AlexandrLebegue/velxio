# LED (led)
Status: complete
Wokwi tag: wokwi-led

## Pins
| pin | role | typical connection |
|---|---|---|
| A | Anode (positive pin) | To 5V through a series resistor (~220-330 ohm) |
| C | Cathode (negative pin) | GND |

## Attributes
| attribute | type | default | role |
|---|---|---|---|
| value | bool | False | LED state (off / on) |
| brightness | number | 1 | Light intensity shown |
| color | string | 'red' | LED body color (red, green, blue, white, yellow, hex...) |
| lightColor | string | None | Color of the emitted light (default derived from color) |
| label | string | '' | Text displayed below the LED |
| flip | bool | False | Flips the LED horizontally |

## Wiring
- Arduino Uno: A -> pin 13 (via 330 ohm series R), C -> GND
- ESP32: A -> GPIO 2 (via 330 ohm series R), C -> GND

## Minimal sketch
Not compiled.
```cpp
// LED: on/off blinking, then 50% PWM brightness
const int PIN_LED = 13;

void setup() {
  pinMode(PIN_LED, OUTPUT);
  digitalWrite(PIN_LED, LOW);
}

void loop() {
  digitalWrite(PIN_LED, HIGH);  // on
  delay(500);
  digitalWrite(PIN_LED, LOW);   // off
  delay(500);
  analogWrite(PIN_LED, 128);    // 50% (PWM-capable pin only)
  delay(500);
  analogWrite(PIN_LED, 0);
  delay(500);
}
```

## Pitfalls
- Always put a series resistor (220-330 ohm) between the output pin and A: without it the LED shorts the pin.
- Mind the polarity: A toward the high side, C to GND; reversed, the LED stays dark.
- analogWrite() only dims the LED on pins that support PWM (Uno: 3, 5, 6, 9, 10, 11).
- Wokwi applies gamma correction (default 2.8): a small PWM duty cycle looks brighter than on real hardware.

## Sources
- https://docs.wokwi.com/parts/wokwi-led: A/C pin names, color/lightColor/label/flip attributes, gamma correction.
- Repo examples (frontend/src/data/examples-circuits.ts): A -> 330 ohm series resistor, C -> GND.
