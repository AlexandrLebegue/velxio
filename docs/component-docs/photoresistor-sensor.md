# Photoresistor Sensor (photoresistor-sensor)
Status: complete
Wokwi tag: wokwi-photoresistor-sensor

## Pins
| pin | role | typical connection |
|---|---|---|
| VCC | Positive power supply (5V) | 5V from the board |
| GND | Ground | GND |
| DO | Digital output (high in the dark, low in the light) | Any digital input |
| AO | Analog output of the LDR voltage divider | Any analog input (e.g. A0) |

## Attributes
| attribute | type | default | role |
|---|---|---|---|
| lux | number | 500 | Current illumination level (lux) |
| threshold | number | 2.5 | DO comparator threshold (V), about 100 lux |
| rl10 | number | 50 | LDR resistance at 10 lux (k ohm) |
| gamma | number | 0.7 | Slope of the log(R) / log(lux) curve |
| ledDO | boolean | false | DO indicator LED state (display only) |
| ledPower | boolean | false | Power LED indicator (display only) |

## Wiring
- Arduino Uno: VCC -> 5V, GND -> GND, AO -> A0, DO -> pin 2
- ESP32: VCC -> 3V3, GND -> GND, AO -> GPIO 34, DO -> GPIO 2

## Minimal sketch
Not compiled.
```cpp
// Photoresistor sensor: report the illumination in lux on the serial port
const int PIN_AO = A0;
const float GAMMA = 0.7; // must match the module gamma attribute
const float RL10 = 50;   // LDR resistance at 10 lux (k ohm)

void setup() {
  Serial.begin(9600);
}

void loop() {
  int raw = analogRead(PIN_AO);
  float volts = raw / 1024.0 * 5.0;
  float r = 2000.0 * volts / (5.0 - volts); // LDR in series with 10 k ohm
  float lux = pow(RL10 * 1e3 * pow(10, GAMMA) / r, 1.0 / GAMMA);
  Serial.print("lux: ");
  Serial.println(lux);
  delay(500);
}
```

## Pitfalls
- DO is high in the dark and low in the light (the on-board LED lights in the light): invert your logic accordingly.
- AO swings 0-5V when powered from 5V: on the ESP32 power the module from 3V3 so the analog output stays in the ADC range.
- LDR resistance varies over orders of magnitude, so the response is logarithmic: use the lux formula above (or a log scale) instead of a linear map.
- In the simulator, change the lux attribute (or the sensor panel) to emulate light; the default threshold of 2.5V is about 100 lux.

## Sources
- https://docs.wokwi.com/parts/wokwi-photoresistor-sensor: VCC/GND/DO/AO pins, lux/threshold/rl10/gamma attributes, DO polarity, lux conversion formula.
- frontend/src/data/examples-circuits.ts: wiring used in Velxio (VCC -> 5V, GND -> GND, AO -> A0).
- frontend/src/simulation/parts/ComplexParts.ts: ledDO and ledPower are display-only properties of the element.
