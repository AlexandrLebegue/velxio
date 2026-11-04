# Pushbutton (pushbutton)
Status: complete
Wokwi tag: wokwi-pushbutton

## Pins
| pin | role | typical connection |
|---|---|---|
| 1.l / 1.r | First contact (left / right side, always tied together) | Digital pin set to INPUT_PULLUP |
| 2.l / 2.r | Second contact (left / right side, always tied together) | GND |

## Attributes
| attribute | type | default | role |
|---|---|---|---|
| color | string | 'red' | Button color |
| pressed | bool | False | Physical state (released / pressed) |
| label | string | '' | Text displayed below the button |
| xray | bool | False | Shows the internal wiring |

## Wiring
- Arduino Uno: 1.l -> pin 2 (pin set to INPUT_PULLUP), 2.l -> GND
- ESP32: 1.l -> GPIO 4 (pin set to INPUT_PULLUP), 2.l -> GND

## Minimal sketch
Not compiled.
```cpp
// Pull-up button driving an LED (reads LOW while pressed)
const int PIN_BTN = 2;
const int PIN_LED = 13;

void setup() {
  pinMode(PIN_BTN, INPUT_PULLUP);
  pinMode(PIN_LED, OUTPUT);
}

void loop() {
  if (digitalRead(PIN_BTN) == LOW) {  // pressed
    digitalWrite(PIN_LED, HIGH);
  } else {
    digitalWrite(PIN_LED, LOW);
  }
}
```

## Pitfalls
- Wokwi simulates contact bouncing by default: add software debouncing in the sketch (or set the bounce="0" attribute in the simulator).
- With INPUT_PULLUP the button reads LOW while pressed; no external resistor is needed.
- The two pins of the same contact (1.l and 1.r) are electrically identical: the choice is purely for layout convenience.
- The xray="1" attribute in the simulator shows the internal contacts (useful to understand the diagram).

## Sources
- https://docs.wokwi.com/parts/wokwi-pushbutton: contacts 1/2 (pins .l/.r), INPUT_PULLUP + GND pattern, simulated bounce.
- Repo examples (frontend/src/data/examples-circuits.ts): 1.l -> pin 2, 2.l -> GND.
