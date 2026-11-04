# Pushbutton (pushbutton)
Statut : complet
Tag Wokwi : wokwi-pushbutton

## Pins
| broche | rôle | connexion typique |
|---|---|---|
| 1.l / 1.r | Premier contact (côté gauche / droit, toujours reliés) | Pin digital en INPUT_PULLUP |
| 2.l / 2.r | Deuxième contact (côté gauche / droit, toujours reliés) | GND |

## Attributes
| attribut | type | défaut | rôle |
|---|---|---|---|
| color | string | 'red' | Couleur du bouton |
| pressed | bool | False | État physique (libéré / enfoncé) |
| label | string | '' | Texte affiché sous le bouton |
| xray | bool | False | Affiche le câblage interne |

## Wiring
- Arduino Uno : 1.l -> broche 2 (pin en INPUT_PULLUP), 2.l -> GND
- ESP32 : 1.l -> GPIO 4 (pin en INPUT_PULLUP), 2.l -> GND

## Minimal sketch
Non compilé.
```cpp
// Bouton debouncé sur pin pull-up haut : pilote une LED
const int PIN_BTN = 2;
const int PIN_LED = 13;

void setup() {
  pinMode(PIN_BTN, INPUT_PULLUP);
  pinMode(PIN_LED, OUTPUT);
}

void loop() {
  if (digitalRead(PIN_BTN) == LOW) {  // bouton enfoncé
    digitalWrite(PIN_LED, HIGH);
  } else {
    digitalWrite(PIN_LED, LOW);
  }
}
```

## Pitfalls
- Wokwi simule le rebond mécanique par défaut : prévoir un debounce logiciel (délai ou flanc) dans le sketch.
- Avec INPUT_PULLUP, le bouton lit LOW quand il est enfoncé ; ne pas ajouter de résistance externe.
- Les deux pins d'un même contact (1.l et 1.r) sont équivalents : le choix est purement de commodité de câblage.
- L'attribut xray="1" dans le simulateur montre les contacts internes (utile pour comprendre le schéma).

## Sources
- https://docs.wokwi.com/parts/wokwi-pushbutton : contacts 1/2 (pins .l/.r), pattern INPUT_PULLUP + GND, rebond simulé.
- Exemples du dépôt (frontend/src/data/examples-circuits.ts) : 1.l -> pin 2, 2.l -> GND.
