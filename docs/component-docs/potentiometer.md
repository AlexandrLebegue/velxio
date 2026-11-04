# Potentiometer (potentiometer)
Statut : complet
Tag Wokwi : wokwi-potentiometer

## Pins
| broche | rôle | connexion typique |
|---|---|---|
| GND | Masse | GND de la carte |
| SIG | Sortie du curseur | Pin d'entrée analogique (A0, A1, ...) |
| VCC | Tension d'alimentation | 5V (Arduino) ou 3V3 (ESP32) |

## Attributes
| attribut | type | défaut | rôle |
|---|---|---|---|
| min | number | 0 | Valeur minimale du potentiomètre |
| max | number | 1023 | Valeur maximale du potentiomètre |
| value | number | 0 | Position courante du curseur (entre min et max) |
| step | number | 1 | Incrément de la position |
| startDegree | number | -135 | Angle du bouton au minimum (degrés) |
| endDegree | number | 135 | Angle du bouton au maximum (degrés) |

## Wiring
- Arduino Uno : VCC -> 5V, GND -> GND, SIG -> A0
- ESP32 : VCC -> 3V3, GND -> GND, SIG -> GPIO 34 (A0)

## Minimal sketch
Non compilé.
```cpp
// Potentiometer : lit A0 et module la luminosité d'une LED PWM
const int PIN_POT = A0;
const int PIN_LED = 3;

void setup() {
  pinMode(PIN_POT, INPUT);
  pinMode(PIN_LED, OUTPUT);
  Serial.begin(115200);
}

void loop() {
  int value = analogRead(PIN_POT);      // 0..1023 sur Uno
  int brightness = map(value, 0, 1023, 0, 255);
  analogWrite(PIN_LED, brightness);
  Serial.println(value);
  delay(100);
}
```

## Pitfalls
- Brancher VCC et GND même si Wokwi tolère de ne pas le faire (le comportement pourra changer).
- Sur ESP32, l'ADC renvoie 0..4095 (12 bits) au lieu de 0..1023 : adapter les bornes de map().
- Les pins analogiques de l'ESP32 sont les GPIO 32-39, dont 34-39 en entrée uniquement.
- Pour convertir en volts : valeur * (VCC / 1023) sur Uno (5V), valeur * (VCC / 4095) sur ESP32.

## Sources
- https://docs.wokwi.com/parts/wokwi-potentiometer : pins GND/SIG/VCC, attribut value (0-1023), exemple analogRead() sur A0.
- Exemples du dépôt (frontend/src/data/examples-100-days.ts) : VCC -> 3V3, GND -> GND, SIG -> pin analogique.
