# PIR Motion Sensor (pir-motion-sensor)
Status: complete
Wokwi tag: wokwi-pir-motion-sensor

## Pins
| pin | role | typical connection |
|---|---|---|
| VCC | Supply voltage (5V) | 5V from the board |
| GND | Ground | GND |
| OUT | Digital motion output (high while motion is reported) | Any digital input (e.g. 4) |

## Attributes
| attribute | type | default | role |
|---|---|---|---|
| delayTime | number | 5 | Seconds OUT stays high after a motion |
| inhibitTime | number | 1.2 | Seconds the sensor ignores motion once OUT goes low |
| retrigger | string | (empty) | Set to "0" to disable retriggering (extend on new motion) |

## Wiring
- Arduino Uno: VCC -> 5V, GND -> GND, OUT -> pin 4
- ESP32: VCC -> 3V3, GND -> GND, OUT -> GPIO 2

## Minimal sketch
Not compiled.
```cpp
// PIR: print a message when motion starts and drive the on-board LED
const int PIN_PIR = 4;
const int PIN_LED = 13;
bool motionOn = false;

void setup() {
  Serial.begin(9600);
  pinMode(PIN_PIR, INPUT);
  pinMode(PIN_LED, OUTPUT);
}

void loop() {
  bool motion = (digitalRead(PIN_PIR) == HIGH);
  if (motion && !motionOn) {
    Serial.println("Motion detected");
  }
  motionOn = motion;
  // OUT stays high for the delay time (default 5 s); retrigger extends it
  digitalWrite(PIN_LED, motion ? HIGH : LOW);
}
```

## Pitfalls
- OUT is 5V on the module: not safe for 3.3V GPIOs (ESP32) on real hardware without a voltage divider (the simulation accepts 3V3 supply).
- OUT does not follow motion 1:1: it stays high for the delayTime (default 5 s), then the sensor is blind for the inhibitTime (1.2 s).
- Retriggering is on by default: any new motion while OUT is high extends the delay; set retrigger to "0" to disable it.
- In the simulator there is no real infrared detection: click the sensor while running and press "Simulate Motion".

## Sources
- https://docs.wokwi.com/parts/wokwi-pir-motion-sensor: VCC/GND/OUT pins, delayTime/inhibitTime/retrigger attributes, trigger behavior.
- frontend/src/data/examples.ts: Velxio wiring (VCC -> 5V/3.3V, GND, OUT -> pin 4).
