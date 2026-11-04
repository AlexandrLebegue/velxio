# Servo (servo)
Statut : complet
Tag Wokwi : wokwi-servo

## Pins
| broche | rôle | connexion typique |
|---|---|---|
| PWM | Signal de commande | Pin capable de PWM (ex. 9 sur Uno) |
| V+ | Alimentation positive (5V) | 5V de la carte ou alimenteur externe |
| GND | Masse | GND |

## Attributes
| attribut | type | défaut | rôle |
|---|---|---|---|
| angle | number | 0 | Angle courant de l'axe, 0 à 180 degrés |
| horn | string | 'single' | Type de tourelle : "single", "double" ou "cross" |
| hornColor | string | '#ccc' | Couleur de la tourelle (hex) |

## Wiring
- Arduino Uno : PWM -> broche 9, V+ -> 5V, GND -> GND
- ESP32 : PWM -> GPIO 13, V+ -> 5V, GND -> GND

## Minimal sketch
Non compilé.
```cpp
// Servo : balayage continu 0 deg -> 180 deg -> 0 deg
#include <Servo.h>

Servo myServo;
const int PIN_SERVO = 9;

void setup() {
  myServo.attach(PIN_SERVO);
  myServo.write(0);
}

void loop() {
  for (int a = 0; a <= 180; a += 5) {
    myServo.write(a);
    delay(30);
  }
  for (int a = 180; a >= 0; a -= 5) {
    myServo.write(a);
    delay(30);
  }
}
```

## Pitfalls
- La bibliothèque Servo.h (Arduino et cores ESP32) est indispensable : le signal est une PWM 50 Hz codant l'angle.
- Pinneur un servo en 3V3 : le pin 3V3 de l'ESP32 est limité, préférez le pin 5V ou une alim externe pour V+.
- Le regulateur 5V de l'Uno (sous USB) ne fournit que ~500 mA : 2-3 servos maximum sans alim externe.
- Dans Wokwi la course est fixée à 0-180 deg avec butees dures aux deux extremes.

## Sources
- https://docs.wokwi.com/parts/wokwi-servo : pins PWM/V+/GND, course 0-180 deg, attributs horn/hornColor.
- Exemples du dépôt (frontend/src/data/examples.ts) : servo Uno branché en PWM/V+/GND.
