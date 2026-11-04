# Potentiometer (potentiometer)
Status: complete
Wokwi tag: wokwi-potentiometer

## Pins
| pin | role | typical connection |
|---|---|---|
| GND | Ground | GND of the board |
| SIG | Wiper output | Analog input pin (A0, A1, ...) |
| VCC | Supply voltage | 5V (Arduino) or 3V3 (ESP32) |

## Attributes
| attribute | type | default | role |
|---|---|---|---|
| min | number | 0 | Minimum value of the potentiometer |
| max | number | 1023 | Maximum value of the potentiometer |
| value | number | 0 | Current wiper position (between min and max) |
| step | number | 1 | Position increment |
| startDegree | number | -135 | Knob angle at the minimum (degrees) |
| endDegree | number | 135 | Knob angle at the maximum (degrees) |

## Wiring
- Arduino Uno: VCC -> 5V, GND -> GND, SIG -> A0
- ESP32: VCC -> 3V3, GND -> GND, SIG -> GPIO 34 (A0)

## Minimal sketch
Not compiled.
```cpp
// Potentiometer: reads A0 and modulates an LED's PWM brightness
const int PIN_POT = A0;
const int PIN_LED = 3;

void setup() {
  pinMode(PIN_POT, INPUT);
  pinMode(PIN_LED, OUTPUT);
  Serial.begin(115200);
}

void loop() {
  int value = analogRead(PIN_POT);   // 0..1023 on the Uno
  int brightness = map(value, 0, 1023, 0, 255);
  analogWrite(PIN_LED, brightness);
  Serial.println(value);
  delay(100);
}
```

## Pitfalls
- Connect VCC and GND even though Wokwi tolerates leaving them unconnected (behavior may change later).
- On the ESP32 the ADC returns 0..4095 (12 bits) instead of 0..1023: adjust the map() bounds.
- The ESP32 analog pins are GPIO 32-39, of which 34-39 are input-only.
- To convert to volts: value * (VCC / 1023) on the Uno (5V), value * (VCC / 4095) on the ESP32.

## Sources
- https://docs.wokwi.com/parts/wokwi-potentiometer: GND/SIG/VCC pins, value attribute (0-1023), analogRead() example on A0.
- Repo examples (frontend/src/data/examples-100-days.ts): VCC -> 3V3, GND -> GND, SIG -> analog pin.
