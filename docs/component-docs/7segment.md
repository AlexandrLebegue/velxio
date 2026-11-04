# 7 Segment (7segment)
Status: complete
Wokwi tag: wokwi-7segment

## Pins
| pin | role | typical connection |
|---|---|---|
| A, B, C, D, E, F, G | the seven segment outputs | one digital pin each, via a 220 ohm resistor |
| DP | dot (decimal point) | digital pin through 220 ohm resistor, optional |
| COM | common anode/cathode of all segments | 5V if common is anode, GND if common is cathode |
| DIG1-4 | digit enable, one per digit (multi-digit displays) | one digital pin per digit when digits > 1 |
| CLN | colon between digits (clock mode) | digital pin when the colon is enabled |

## Attributes
| attribute | type | default | role |
|---|---|---|---|
| common | string | 'anode' | 'anode' or 'cathode': polarity of the common pin |
| digits | number | 1 | number of digits (1 to 4) |
| colon | boolean | false | show the CLN colon when true |
| colonValue | boolean | false | whether the colon is currently lit |
| color | string | 'red' | LED color of the segments (name or hex code) |
| offColor | string | '#444' | color of unlit segments |
| background | string | 'black' | color of the display background |
| pins | string | 'top' | side of the package where the pins are drawn |
| values | array | [0, 0, 0, 0, 0, 0, 0, 0] | value currently shown on each digit |

## Wiring
- Arduino Uno: A -> 2, B -> 3, C -> 4, D -> 5, E -> 6, F -> 7, G -> 8, DP -> 9, COM -> GND (common cathode)
- ESP32: A -> GPIO 4, B -> GPIO 5, C -> GPIO 16, D -> GPIO 17, E -> GPIO 18, F -> GPIO 19, G -> GPIO 23, DP -> GPIO 21, COM -> GND

## Minimal sketch
Not compiled.
```cpp
// Common-cathode single digit: segments A-G on pins 2-8, COM tied to GND
const int SEG[7] = {2, 3, 4, 5, 6, 7, 8}; // A, B, C, D, E, F, G
// Bit patterns for digits 0-9, bits = A B C D E F G
const uint8_t DIGIT[10] = {0x3F, 0x06, 0x5B, 0x4F, 0x66, 0x6D, 0x7D, 0x07, 0x7F, 0x6F};
int value = 0;
void setup() {
  for (int i = 0; i < 7; i++) {
    pinMode(SEG[i], OUTPUT); // common cathode: HIGH lights a segment
  }
}
void loop() {
  uint8_t p = DIGIT[value];
  for (int i = 0; i < 7; i++) digitalWrite(SEG[i], p & (1 << i));
  value = (value + 1) % 10;
  delay(500); // count up one digit every half second
}
```

## Pitfalls
- Put a 220-330 ohm series resistor on every segment pin; driving the segments bare can destroy the LEDs and the GPIOs.
- The default common is 'anode': segments light when driven LOW and COM must go to 5V. Use common 'cathode' to drive HIGH with COM on GND.
- Multi-digit mode needs the 8 segment pins plus one pin per DIG digit; use the SevSeg library or a 74HC595 shift register to save pins.

## Sources
- https://docs.wokwi.com/parts/wokwi-7segment: pin names (A-G, DP, COM, DIG1-4, CLN), attributes and defaults, anode/cathode lighting behavior.
- Repo examples (frontend/src/data/examples.ts): common-cathode wiring with COM -> GND and one digital pin per segment.
