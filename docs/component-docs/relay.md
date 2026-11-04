# Relay (SPDT) (relay)
Status: complete
Wokwi tag: velxio-relay

## Pins
| pin | role | typical connection |
|---|---|---|
| COIL+ | Coil power supply | 5V (or 12V/24V per coil_voltage) |
| COIL- | Coil return | NPN driver collector (or GND) |
| NO | Normally-open contact | Switched supply for the load |
| COM | Common contact | Load input |
| NC | Normally-closed contact | Supply for the load at rest |

## Attributes
| attribute | type | default | role |
|---|---|---|---|
| coil_voltage | number | 5 | Nominal coil voltage (V); options 5/12/24; contacts pull in at 75% |
| coil_resistance | number | 70 | Coil resistance (ohm); coil current = voltage / R |
| include_flyback | boolean | true | Integrated flyback diode across the coil |

## Wiring
- Arduino Uno: 5V -> COIL+, COIL- -> Q1 collector, pin 9 -> Q1 base (1k), Q1 emitter -> GND, COM -> load -> GND, NO -> 5V
- ESP32: 5V -> COIL+, COIL- -> Q1 collector, GPIO 27 -> Q1 base (1k), Q1 emitter -> GND, COM -> load -> GND, NO -> 5V

## Minimal sketch
Not compiled.
```cpp
// Relay: switch a load on/off with an NPN transistor driver
const int PIN_DRIVE = 9; // transistor base (1 k ohm series resistor)

void setup() {
  pinMode(PIN_DRIVE, OUTPUT);
  digitalWrite(PIN_DRIVE, LOW); // de-energized at start
}

void loop() {
  // Energize: 5V -> COIL+ -> COIL- -> collector -> GND, NO closes to COM
  digitalWrite(PIN_DRIVE, HIGH);
  delay(2000);
  // De-energize: the flyback diode clamps the coil kick
  digitalWrite(PIN_DRIVE, LOW);
  delay(2000);
}
```

## Pitfalls
- A 5 V / 70 ohm coil draws ~71 mA, above the 40 mA per-pin limit of the Uno and ESP32: always drive the coil through a transistor.
- Keep the flyback diode in the circuit (integrated by default, include_flyback): without it the inductive spike destroys the transistor when the coil drops.
- Contacts pull in at 75% of coil_voltage: with 5 V and 70 ohm the margin is small, so a sagging supply may not release the contacts reliably.
- Put the high-voltage load on the contact side and keep the coil's logic side at or below 5 V.

## Sources
- https://docs.wokwi.com/parts/velxio-relay: no public page (404); velxio-relay is a custom part defined in this repo.
- scripts/component-overrides.json: pin names (COIL+, COIL-, NO, COM, NC), attributes, defaults, 75% pull-in threshold.
- frontend/src/data/examples-circuits.ts: relay control example (NPN low-side driver, COM -> load -> GND, NO -> 5V).
