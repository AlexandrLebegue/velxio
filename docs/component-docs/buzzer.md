# Buzzer (buzzer)
Statut : complet
Tag Wokwi : wokwi-buzzer

## Pins
| broche | rôle | connexion typique |
|---|---|---|
| 1 | Pin négatif (noir) | GND |
| 2 | Pin positif (rouge) | Pin digital piloté par tone() |

## Attributes
| attribut | type | défaut | rôle |
|---|---|---|---|
| hasSignal | bool | False | Présence d'un signal sonore sur le composant |
| mode | string | 'smooth' | Mode de rendu : "smooth" (mélodies) ou "accurate" (signaux complexes) |
| volume | string | '1.0' | Volume du son simulé, entre "0.01" et "1.0" |

## Wiring
- Arduino Uno : 2 (positif) -> broche 8, 1 (négatif) -> GND
- ESP32 : 2 (positif) -> GPIO 5, 1 (négatif) -> GND

## Minimal sketch
Non compilé.
```cpp
// Buzzer piezo : joue trois notes avec tone()
const int PIN_BUZZER = 8;

void setup() {
  pinMode(PIN_BUZZER, OUTPUT);
}

void loop() {
  tone(PIN_BUZZER, 523);   // note C5
  delay(200);
  tone(PIN_BUZZER, 659);   // note E5
  delay(200);
  tone(PIN_BUZZER, 784);   // note G5
  delay(200);
  noTone(PIN_BUZZER);      // silence
  delay(400);
}
```

## Pitfalls
- Dans Wokwi, le pin 1 est le négatif (GND) et le pin 2 le positif (pin de commande) : respecter cette polarité dans le schéma.
- Le mode "smooth" (défaut) est adapté aux mélodies tone() ; passer à "accurate" pour des signaux complexes, au prix de clics audibles.
- Appeler noTone() (ou tone() avec une durée) après chaque note, sinon le son continue indéfiniment.
- L'attribut volume n'a d'effet que dans le simulateur, pas sur le matériel réel.

## Sources
- https://docs.wokwi.com/parts/wokwi-buzzer : pins 1 (négatif) / 2 (positif), modes smooth/accurate, volume, exemple tone(8, 262, 250).
- Exemples du dépôt (frontend/src/data/examples-100-days.ts) : usage des pins 1 et 2 avec une carte Arduino.
