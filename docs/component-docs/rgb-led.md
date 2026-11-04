# RGB Led (rgb-led)
Status: complete
Wokwi tag: wokwi-rgb-led

## Pins
| pin | role | typical connection |
|---|---|---|
| R | Red channel | To the board through a series resistor (~220 ohm) |
| G | Green channel | To the board through a series resistor (~220 ohm) |
| B | Blue channel | To the board through a series resistor (~220 ohm) |
| COM | Common pin | GND (common cathode) or 5V (common anode) |

## Attributes
| attribute | type | default | role |
|---|---|---|---|
| ledRed | number | 0 | Red channel intensity |
| ledGreen | number | 0 | Green channel intensity |
| ledBlue | number | 0 | Blue channel intensity |
| common | string | 'anode' | COM pin polarity: "anode" or "cathode" |

## Wiring
- Arduino Uno: R -> pin 9 (via 220 ohm R), G -> pin 10 (via 220 ohm R), B -> pin 11 (via 220 ohm R), COM -> GND
- ESP32: R -> GPIO 5 (via 220 ohm R), G -> GPIO 18 (via 220 ohm R), B -> GPIO 19 (via 220 ohm R), COM -> GND

## Minimal sketch
Not compiled.
```cpp
// Common-cathode RGB LED: red, green, blue via PWM
const int PIN_R = 9, PIN_G = 10, PIN_B = 11;

void setup() {
  pinMode(PIN_R, OUTPUT);
  pinMode(PIN_G, OUTPUT);
  pinMode(PIN_B, OUTPUT);
}

void loop() {
  analogWrite(PIN_R, 255);  // red
  analogWrite(PIN_G, 0);
  analogWrite(PIN_B, 0);
  delay(500);
  analogWrite(PIN_R, 0);    // green
  analogWrite(PIN_G, 255);
  analogWrite(PIN_B, 0);
  delay(500);
  analogWrite(PIN_R, 0);    // blue
  analogWrite(PIN_G, 0);
  analogWrite(PIN_B, 255);
  delay(500);
}
```

## Pitfalls
- One series resistor per channel (~220 ohm): never share a single resistor between two channels.
- Check the common pin type: anode = COM to 5V with low-side drive; cathode = COM to GND with high-side drive.
- In Wokwi, the common attribute changes the simulated polarity: set it to "cathode" when COM is wired to GND (PWM values inverted).

## Sources
- https://docs.wokwi.com/parts/wokwi-rgb-led: R/G/B/COM pins, common attribute (default "anode").
- Repo examples (frontend/src/data/examples-100-days.ts): one 220 ohm resistor per channel, COM -> GND.
