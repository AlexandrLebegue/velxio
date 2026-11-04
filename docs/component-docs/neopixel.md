# Neopixel (neopixel)
Status: complete
Wokwi tag: wokwi-neopixel

## Pins
| pin | role | typical connection |
|---|---|---|
| DIN | data input (latched data line) | digital output pin (e.g. 6 on Uno) |
| DOUT | data output to the next pixel in the chain | DIN of the next NeoPixel |
| VDD | supply voltage | 5V on Uno, 3V3 on ESP32 |
| VSS | ground | GND |

## Attributes
| attribute | type | default | role |
|---|---|---|---|
| r | number | 0 | red channel of the LED, 0 to 255 |
| g | number | 0 | green channel of the LED, 0 to 255 |
| b | number | 0 | blue channel of the LED, 0 to 255 |

## Wiring
- Arduino Uno: DIN -> 6, VDD -> 5V, VSS -> GND
- ESP32: DIN -> GPIO 4, VDD -> 3V3, VSS -> GND

## Minimal sketch
Not compiled.
```cpp
// One WS2812 (NeoPixel) on pin 6, cycling red, green, blue
#include <Adafruit_NeoPixel.h>
#define LED_PIN 6
Adafruit_NeoPixel pixel(1, LED_PIN, NEO_GRB + NEO_KHZ800);
void setup() {
  pixel.begin(); // initialize the pixel
}
void loop() {
  pixel.setPixelColor(0, pixel.Color(150, 0, 0)); // red
  pixel.show();
  delay(300);
  pixel.setPixelColor(0, pixel.Color(0, 150, 0)); // green
  pixel.show();
  delay(300);
  pixel.setPixelColor(0, pixel.Color(0, 0, 150)); // blue
  pixel.show();
  delay(300);
}
```

## Pitfalls
- The WS2812 chip is a 5V device: power VDD from the Uno 5V rail, not 3.3V; longer strips need their own 5V supply.
- Put a 300-500 ohm series resistor between the microcontroller pin and DIN on real hardware to protect the data line.
- Chain pixels DOUT -> DIN; the whole chain shares one data line and must share a common ground.
- Requires the Adafruit_NeoPixel library; on the ESP32 the 3V3 GPIO output is usually read correctly by the pixel data input.

## Sources
- https://docs.wokwi.com/parts/wokwi-neopixel: pin names (DIN, DOUT, VDD, VSS), chaining method, Adafruit NeoPixel example with LED pin 6.
- Repo examples (frontend/src/data/examples.ts): VDD -> 5V (Uno) and 3V3 (ESP32), VSS -> GND wiring, r/g/b properties.
