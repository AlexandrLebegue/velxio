# Stepper Motor (stepper-motor)
Status: complete
Wokwi tag: wokwi-stepper-motor

## Pins
| pin | role | typical connection |
|---|---|---|
| A+ | coil A positive lead | A4988 2A (or MCU pin when driven directly) |
| A- | coil A negative lead | A4988 2B |
| B+ | coil B positive lead | A4988 1A |
| B- | coil B negative lead | A4988 1B |

## Attributes
| attribute | type | default | role |
|---|---|---|---|
| angle | number | 0 | current rotation angle of the motor in degrees |
| value | string | '' | value shown on the small display of the part |
| units | string | '' | unit text shown next to the value |
| arrow | string | '' | color of the position arrow, empty hides it |
| display | string | 'steps' | what the display shows: 'steps', 'angle' or 'none' |
| gearRatio | string | '1:1' | gear ratio: '1:1' = 200 steps/rev, '2:1' = 400 |
| size | string | '23' | NEMA size of the motor ('8', '11', '14', '17', '23', '34') |

## Wiring
- Arduino Uno: A+ -> A4988 2A, A- -> A4988 2B, B+ -> A4988 1A, B- -> A4988 1B (driver: STEP -> 3, DIR -> 4)
- ESP32: A+ -> A4988 2A, A- -> A4988 2B, B+ -> A4988 1A, B- -> A4988 1B (driver: STEP -> GPIO 26, DIR -> GPIO 27)

## Minimal sketch
Not compiled.
```cpp
// Bipolar stepper through an A4988: STEP on pin 3, DIR on pin 4, coils on 1A/1B/2A/2B
const int STEP_PIN = 3;
const int DIR_PIN = 4;
void setup() {
  pinMode(STEP_PIN, OUTPUT);
  pinMode(DIR_PIN, OUTPUT);
  digitalWrite(DIR_PIN, HIGH); // pick the rotation direction
}
void loop() {
  digitalWrite(STEP_PIN, HIGH);
  delayMicroseconds(1000); // one full step, ~1000 steps/s
  digitalWrite(STEP_PIN, LOW);
  delayMicroseconds(1000);
  static int steps = 0; // reverse after one full turn (200 steps)
  if (++steps >= 200) {
    steps = 0;
    digitalWrite(DIR_PIN, !digitalRead(DIR_PIN));
  }
}
```

## Pitfalls
- The coils need a driver chip (A4988) that can source the coil current; direct MCU GPIO wiring only works in Wokwi's digital simulation.
- A 200-steps/revolution motor moves 1.8 degrees per full step; half-stepping gives 0.9 degrees per step.
- The simulated display only updates at half-step resolution, even if you request finer microsteps.
- Microstepping on the A4988 (MS1/MS2/MS3) must be set before power is applied to the driver.

## Sources
- https://docs.wokwi.com/parts/wokwi-stepper-motor: pins, attributes (arrow, display, gearRatio, size), 1.8 degrees per step, 200/400 steps per revolution.
- Repo examples (frontend/src/data/examples.ts): motor-to-A4988 coil wiring (1A/1B to B+/B-, 2A/2B to A+/A-) and STEP/DIR on Uno 3/4, ESP32 26/27.
