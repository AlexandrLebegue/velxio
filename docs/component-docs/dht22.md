# DHT22 (dht22)
Status: complete
Wokwi tag: wokwi-dht22

## Pins
| pin | role | typical connection |
|---|---|---|
| VCC | Positive voltage (3.3V-5V) | 5V from the board (3V3 on the ESP32) |
| SDA | Single-wire digital data (open-drain) | Any digital pin (e.g. 7), pull-up to VCC |
| NC | Not connected | none |
| GND | Ground | GND |

## Attributes
| attribute | type | default | role |
|---|---|---|---|
| temperature | number | 24 | Initial temperature value (celsius) |
| humidity | number | 40 | Initial relative humidity (percentage) |

## Wiring
- Arduino Uno: VCC -> 5V, GND -> GND, SDA -> pin 7
- ESP32: VCC -> 3V3, GND -> GND, SDA -> GPIO 27

## Minimal sketch
Not compiled.
```cpp
// DHT22: read temperature and relative humidity once every 2 seconds
#include <DHT.h>

#define PIN_DHT 7
#define TYPE_DHT DHT22
DHT dht(PIN_DHT, TYPE_DHT);

void setup() {
  Serial.begin(115200);
  dht.begin();
}

void loop() {
  float temp = dht.readTemperature();
  float hum = dht.readHumidity();
  if (isnan(temp) || isnan(hum)) {
    Serial.println("Sensor read failed");
  } else {
    Serial.print("Temp C: ");
    Serial.print(temp);
    Serial.print("  Humidity %: ");
    Serial.println(hum);
  }
  delay(2000);
}
```

## Pitfalls
- The single-wire bus is open-drain: a 4.7k-10k pull-up between VCC and SDA is needed (usually built into the module).
- On the ESP32 use the "DHT sensor library for ESPx": other DHT libraries are not reliable there (Wokwi docs warning).
- The sensor only emits one measurement every 1-2 s: read with a delay, and check the values for NaN after a failed read.
- When powered from 5V the SDA signal is 5V, which is not safe for 3.3V GPIOs (ESP32): power from 3V3.

## Sources
- https://docs.wokwi.com/parts/wokwi-dht22: pins, attributes, ESP32 library warning; repo examples: Velxio wiring (VCC -> 5V/3.3V, GND, SDA -> pin 7).
