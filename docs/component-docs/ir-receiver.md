# IR Receiver (ir-receiver)
Status: complete
Wokwi tag: wokwi-ir-receiver

## Pins
| pin | role | typical connection |
|---|---|---|
| GND | Ground | GND |
| VCC | Positive voltage | 5V on Uno, 3V3 on ESP32 |
| DAT | Demodulated digital output (active low) | Pin 2 on Uno, GPIO 15 on ESP32 |

## Attributes
| attribute | type | default | role |
|---|---|---|---|
| irAddress | string | '0x00' | NEC address field sent when the receiver is clicked |
| irCommand | string | '0x45' | NEC command field sent when the receiver is clicked |
| channel | string | '' | Linking channel shared with an IR remote part |

## Wiring
- Arduino Uno: VCC -> 5V, GND -> GND, DAT -> pin 2
- ESP32: VCC -> 3V3, GND -> GND, DAT -> GPIO 15

## Minimal sketch
Not compiled.
```cpp
// IR receiver: decode NEC commands from a remote with IRremote
#include <IRremote.hpp>

const int RECV_PIN = 2;

void setup() {
  Serial.begin(9600);
  IrReceiver.begin(RECV_PIN, ENABLE_LED_FEEDBACK);
  Serial.println("IR receiver ready, waiting for a button press");
}

void loop() {
  if (IrReceiver.decode()) {
    if (IrReceiver.decodedIRData.protocol == UNKNOWN) {
      Serial.println("Unknown protocol");
    } else {
      Serial.print("address 0x");
      Serial.print(IrReceiver.decodedIRData.address, HEX);
      Serial.print("  command 0x");
      Serial.println(IrReceiver.decodedIRData.command, HEX);
    }
    IrReceiver.resume();
  }
}
```

## Pitfalls
- The demodulator output is active low (line pulled down for each mark): the library inverts it, so do not invert it again in custom timing code.
- No wire connects the remote and the receiver in Wokwi: the two parts are linked through the air, on the same channel.
- Clicking the running receiver sends its configured NEC address/command pair, which is handy for testing without a remote part.

## Sources
- https://docs.wokwi.com/parts/wokwi-ir-receiver: pins (GND/VCC/DAT), 38 kHz receiver, NEC address/command fields, IRRemote and IRMP libraries.
- Repo examples (frontend/src/data/examples-infrared.ts): wiring DAT -> Uno pin 2 / ESP32 GPIO 15, irAddress/irCommand/channel properties.
