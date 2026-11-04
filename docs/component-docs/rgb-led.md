# RGB Led (rgb-led)
Statut : complet
Tag Wokwi : wokwi-rgb-led

## Pins
| broche | rôle | connexion typique |
|---|---|---|
| R | Canale rouge | Vers la carte via résistance série (~220 Ω) |
| G | Canale vert | Vers la carte via résistance série (~220 Ω) |
| B | Canale bleu | Vers la carte via résistance série (~220 Ω) |
| COM | Broche commune | GND (cathode commune) ou 5V (anode commune) |

## Attributes
| attribut | type | défaut | rôle |
|---|---|---|---|
| ledRed | number | 0 | Intensité du canal rouge |
| ledGreen | number | 0 | Intensité du canal vert |
| ledBlue | number | 0 | Intensité du canal bleu |
| common | string | 'anode' | Polarité du pin COM : "anode" ou "cathode" |

## Wiring
- Arduino Uno : R -> broche 9 (via R 220 Ω), G -> broche 10 (via R 220 Ω), B -> broche 11 (via R 220 Ω), COM -> GND
- ESP32 : R -> GPIO 5 (via R 220 Ω), G -> GPIO 18 (via R 220 Ω), B -> GPIO 19 (via R 220 Ω), COM -> GND

## Minimal sketch
Non compilé.
```cpp
// LED RGB a cathode commune : rouge, vert, bleu en PWM
const int PIN_R = 9, PIN_G = 10, PIN_B = 11;

void setup() {
  pinMode(PIN_R, OUTPUT);
  pinMode(PIN_G, OUTPUT);
  pinMode(PIN_B, OUTPUT);
}

void loop() {
  analogWrite(PIN_R, 255);  // rouge
  analogWrite(PIN_G, 0);
  analogWrite(PIN_B, 0);
  delay(500);
  analogWrite(PIN_R, 0);    // vert
  analogWrite(PIN_G, 255);
  analogWrite(PIN_B, 0);
  delay(500);
  analogWrite(PIN_R, 0);    // bleu
  analogWrite(PIN_G, 0);
  analogWrite(PIN_B, 255);
  delay(500);
}
```

## Pitfalls
- Une résistance série par canal (~220 Ω) : ne jamais relier deux canaux à la même résistance.
- Vérifier le type de pin commun : anode = COM vers 5V et sorties basses ; cathode = COM vers GND et sorties hautes.
- En Wokwi, l'attribut common change la polarité simulée : le mettre à "cathode" si COM est câblé sur GND (valeurs PWM inversées).

## Sources
- https://docs.wokwi.com/parts/wokwi-rgb-led : pins R/G/B/COM, attribut common (défaut "anode").
- Exemples du dépôt (frontend/src/data/examples-100-days.ts) : un R 220 Ω par canal, COM -> GND.
