# Buzzer (buzzer)
Status: complete
Wokwi tag: wokwi-buzzer

## Pins
| pin | role | typical connection |
|---|---|---|
| 1 | Negative (black) pin | GND |
| 2 | Positive (red) pin | Digital pin driven by tone() |

## Attributes
| attribute | type | default | role |
|---|---|---|---|
| hasSignal | bool | False | Whether a sound signal is present on the part |
| mode | string | 'smooth' | Sound rendering mode: "smooth" (melodies) or "accurate" (complex signals) |
| volume | string | '1.0' | Simulated sound volume, between "0.01" and "1.0" |

## Wiring
- Arduino Uno: 2 (positive) -> pin 8, 1 (negative) -> GND
- ESP32: 2 (positive) -> GPIO 5, 1 (negative) -> GND

## Minimal sketch
Not compiled.
```cpp
// Piezo buzzer: plays three notes with tone()
const int PIN_BUZZER = 8;

void setup() {
  pinMode(PIN_BUZZER, OUTPUT);
}

void loop() {
  tone(PIN_BUZZER, 523);   // C5 note
  delay(200);
  tone(PIN_BUZZER, 659);   // E5 note
  delay(200);
  tone(PIN_BUZZER, 784);   // G5 note
  delay(200);
  noTone(PIN_BUZZER);      // silence
  delay(400);
}
```

## Pitfalls
- In Wokwi, pin 1 is the negative one (GND) and pin 2 the positive one (drive pin): follow this polarity in the diagram.
- Use "smooth" mode (default) for tone() melodies; switch to "accurate" for complex signals, at the cost of audible clicks.
- Call noTone() (or tone() with a duration) after each note, otherwise the sound never stops.
- The volume attribute only affects the simulation, not real hardware.

## Sources
- https://docs.wokwi.com/parts/wokwi-buzzer: pins 1 (negative) / 2 (positive), smooth/accurate modes, volume, tone(8, 262, 250) example.
- Repo examples (frontend/src/data/examples-100-days.ts): pins 1 and 2 used with an Arduino board.
