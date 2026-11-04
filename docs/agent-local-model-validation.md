# Tests du modèle local — 4 novembre 2026

Les trois projets produisent un build réel réussi et une recompilation indépendante cohérente. Le modèle utilisé est **qwen3.8-27b**, via le serveur local fourni, avec le véritable harness **OpenCode 1.19.3** et les outils MCP de l'agent. Aucun programme final n'a été écrit ou corrigé manuellement pour obtenir ces résultats.

Ces tests sont entièrement backend. Le transport de l'éditeur est remplacé par un adaptateur de test qui conserve les projets et valide les broches. `run_project` appelle les routes de compilation de production ; son état `compiled` ne confirme aucune exécution électronique.

| Scénario | Cohérence du circuit et du code relue | Flash / RAM | Builds finaux |
| --- | --- | --- | --- |
| LED externe / Uno | D2 → résistance 1 kΩ → anode ; cathode → GND. Code sur D2, alternance HIGH/LOW avec `delay(500)`, messages `LED_ON` / `LED_OFF`. | 1 992 / 202 octets | 2 succès ; HEX identiques |
| Servo 45° / Nano | V+ → 5V, GND commun, PWM → D9. `Servo.attach(9)`, `write(45)`, message toutes les secondes. | 2 852 / 247 octets | 2 succès ; HEX identiques |
| E-ink / ESP32 | Panneau 200×200 SSD1681, pilote `GxEPD2_154_D67`. MOSI 23, SCK 18, CS 5, DC 17, RST 16, BUSY 4, alimentation 3V3/GND. Texte et cadre noir sur fond blanc dans la boucle paginée. | 366 605 / 22 336 octets | 2 succès après correction par le modèle |

Les sources et la cible envoyées au compilateur correspondent aux sources finales dans les trois cas. Le cache des réponses de compilation est contourné. Pour l'ESP32, les images fusionnées de 4 Mio diffèrent de 65 octets, exclusivement dans l'empreinte ELF de la description d'application, le checksum et le hash de l'image. Code, données, bootloader et partitions sont identiques hors de ces champs ; esptool valide les deux images. Le rapport `firmware-comparison.json` conserve cette comparaison.

## Ce que les tests ont permis de corriger

- **Instances de composants ambiguës** : Qwen utilisait `component:led` comme `metadataId`, ou omettait des champs obligatoires. Les références fournissent maintenant un `instance_template` complet ; la recherche expose le `metadataId` sans préfixe. `create_project` renvoie aussi la carte créée et les chemins des sources.
- **Recherche trop littérale** : la requête composée `e-ink epaper 1.54` ne trouvait rien. Le contrat agent essaie les mots séparément si nécessaire, expose `query_used` et fournit `next_offset` pour la pagination.
- **API de bibliothèque difficile à retrouver** : la référence du panneau expose maintenant `example_references`, permettant de lire l'exemple GxEPD2 existant au lieu de chercher des headers hors du projet.
- **Environnement ESP32 incomplet** : la première série s'arrêtait dans esptool sur l'absence de `serial`. La reprise utilise le Python du venv avec les dépendances nécessaires ; le cache de compilation du script dispose aussi d'un répertoire isolé accessible en écriture.

Après le correctif des instances, LED et servo réussissent avec deux lectures de références chacun : LED/résistance pour l'Uno, servo/broches Nano pour le second cas. Le servo ne rencontre aucune erreur d'outil. Pour la LED, Qwen tente d'abord `/components/led-1`, refusé car `components` est un tableau, puis remplace correctement le tableau complet. Les tours agent durent respectivement 60,9 secondes et 57 secondes, avec 11 et 10 appels MCP ; ces durées excluent la recompilation indépendante.

L'e-ink reste moins fluide. La reprise effectue trois recherches distinctes au lieu de six recherches dont quatre pages identiques. Elle lit le panneau et son exemple, tente aussi un exemple inexistant, puis corrige un ajout via `/components/-` refusé. Le premier code utilise `drawFrame`, absent d'Adafruit GFX ; le compilateur le refuse et **Qwen remplace lui-même cet appel par deux `fillRect`**, puis obtient un build réussi. Ce tour dure 162 secondes, avec 21 appels MCP et trois erreurs d'outils récupérées ; la recompilation indépendante est exclue de cette durée. Ce parcours démontre la récupération après erreur, pas une réussite du premier coup ni une garantie générale de fiabilité du modèle.

## Preuves et reproduction

Les projets exportés sont importables séparément : [LED](/tmp/velxio-qwen-validation/backend-artifacts/blink/project.vlx), [Nano/servo](/tmp/velxio-qwen-validation/backend-artifacts/servo-nano/project.vlx), [ESP32/e-ink](/tmp/velxio-qwen-validation/backend-replay/eink-esp32/project.vlx).

Les rapports conservent les demandes, sources, appels d'outils, diagnostics et empreintes : [LED](/tmp/velxio-qwen-validation/backend-artifacts/blink/report.json), [servo](/tmp/velxio-qwen-validation/backend-artifacts/servo-nano/report.json), [e-ink après reprise](/tmp/velxio-qwen-validation/backend-replay/eink-esp32/report.json), [comparaison ESP32](/tmp/velxio-qwen-validation/backend-replay/eink-esp32/firmware-comparison.json). La première tentative ESP32 en échec est conservée séparément dans `backend-artifacts/eink-esp32`.

Le script réutilisable est [test-agent-backend-local.py](../scripts/test-agent-backend-local.py). Les paramètres et prérequis sont décrits dans [agent-connectable.md](agent-connectable.md#évaluation-backend-avec-un-modèle-local-réel). Toolchain utilisée : Arduino CLI 1.5.1, AVR 1.8.6, ESP32 2.0.17, Servo 1.3.0, GxEPD2 1.6.9, Adafruit GFX 1.13.0 et BusIO 1.17.4. L'ESP32 passe par le fallback Arduino CLI ; le compilateur ESP-IDF dédié n'est pas installé ici.

Vérification du contrat : **24 tests unitaires backend réussis**, plus l'intégration réelle OpenCode/MCP avec modèle déterministe. Les générations des trois projets ci-dessus utilisent bien le modèle local réel.

Ni le clignotement mesuré, ni l'angle effectif du servo, ni les pixels affichés, ni le rendu des fils dans l'éditeur ne sont validés par cette série. Un passage par scénario, avec reprise de l'e-ink, ne constitue pas une mesure statistique de fiabilité.
