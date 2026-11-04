# LED (led)
Statut : complet
Tag Wokwi : wokwi-led

## Pins
| broche | rôle | connexion typique |
|---|---|---|
| A | Anode (pin positive) | Vers 5V par l'intermédiaire d'une résistance série (~220-330 Ω) |
| C | Cathode (pin négative) | GND |

## Attributes
| attribut | type | défaut | rôle |
|---|---|---|---|
| value | bool | False | État de la LED (éteinte / allumée) |
| brightness | number | 1 | Intensité lumineuse affichée |
| color | string | 'red' | Couleur du boîtier (red, green, blue, white, yellow, hex...) |
| lightColor | string | None | Couleur de la lumière (défaut : dérivée de color) |
| label | string | '' | Texte affiché sous la LED |
| flip | bool | False | Retourne la LED horizontalement |

## Wiring
- Arduino Uno : A -> broche 13 (via R série 330 Ω), C -> GND
- ESP32 : A -> GPIO 2 (via R série 330 Ω), C -> GND

## Minimal sketch
Non compilé.
```cpp
// LED : allumage / extinction, puis demi-brillance en PWM
const int PIN_LED = 13;

void setup() {
  pinMode(PIN_LED, OUTPUT);
  digitalWrite(PIN_LED, LOW);
}

void loop() {
  digitalWrite(PIN_LED, HIGH);  // allumée
  delay(500);
  digitalWrite(PIN_LED, LOW);   // éteinte
  delay(500);
  analogWrite(PIN_LED, 128);    // 50 % (broche PWM uniquement)
  delay(500);
  analogWrite(PIN_LED, 0);
  delay(500);
}
```

## Pitfalls
- Toujours placer une résistance série (220-330 Ω) entre la broche de sortie et A : sans elle la LED court-circuite le pin.
- Respecter la polarité : A vers le haut (côté pin), C vers GND ; inversée, la LED ne s'allume pas.
- analogWrite() ne module la luminosité que sur les broches capables de PWM (Uno : 3, 5, 6, 9, 10, 11).
- Wokwi applique une correction gamma (2.8 par défaut) : un petit duty cycle PWM paraît plus lumineux qu'en réel.

## Sources
- https://docs.wokwi.com/parts/wokwi-led : noms de pins A/C, attributs color/lightColor/label/flip, correction gamma.
- Exemples du dépôt (frontend/src/data/examples-circuits.ts) : fil A -> résistance série 330 Ω, C -> GND.
