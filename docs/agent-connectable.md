# Agent IA dans l’éditeur

Le bouton **Agent IA**, en bas à droite, ouvre la conversation. Le menu File donne aussi accès au panneau et à ses paramètres. Le moteur utilisé est OpenCode 1.19.3 ; les requêtes au modèle et les clés restent côté serveur.

Les libellés suivent la langue du site : **AI agent** sur la version anglaise, **Agent IA** sur la version française. Le panneau reprend les thèmes de l’éditeur. Le raisonnement fourni par le modèle apparaît dans un bloc repliable distinct de sa réponse. Les étapes gardent leur statut, leur durée et leurs détails après la fin du tour et après rechargement.

## Utilisation

1. Ouvrir le projet dans l’éditeur, ou un espace vide pour demander un starter.
2. Ouvrir les paramètres IA et renseigner l’URL de base de l’API compatible Chat Completions, l’identifiant exact du modèle et, si nécessaire, sa clé.
3. Tester la connexion : le test vérifie le streaming et demande un appel d’outil sans effet.
4. Enregistrer, puis demander une modification. Exemple : « Fais clignoter la LED et affiche son état sur le port série. Lance et observe la simulation. »

Le serveur doit pouvoir joindre le LLM. Pour un moteur local, l’URL peut être `http://127.0.0.1:11434/v1`. Dans Docker, cette adresse désigne le conteneur : utiliser le nom du service LLM ou l’adresse réseau de son hôte.

L’agent travaille sur des fichiers ordinaires dans un dossier propre à la conversation. Le manifeste `.velxio.json` associe automatiquement ce dossier à son projet. Le modèle n’envoie ni tableau `files` ni `project_id` pour lancer le projet actif.

Les sources sont appliquées au lancement ou à la fin du tour. Une modification manuelle concurrente est conservée et produit un conflit explicite. Le bouton de téléchargement permet de récupérer le snapshot de l’agent en `.vlx`. « Arrêter » interrompt le tour et empêche une compilation en cours de laisser ensuite une simulation active ; le compilateur déjà admis peut terminer son travail.

Pour câbler, l’agent peut appeler `connect_pins` avec deux endpoints `{componentId, pinName}`, puis `disconnect_wire` avec un ID de fil. `set_component_properties` fusionne les propriétés d’un composant existant. Velxio valide les broches contre les pads réels, résout les aliases, calcule les coordonnées et applique la topologie en une seule opération. `update_circuit` reste disponible pour les patches avancés et traverse les mêmes contrôles. Une broche inconnue est refusée avec ses alternatives valides ; un fil dessiné au bon endroit ne suffit pas à valider une connexion.

## Remplacer une carte et éviter les lectures répétées

`change_board({"board":"esp32"})` remplace la carte active dans le projet existant. `board_id` permet de cibler une autre carte ; `pin_map` remappe les connexions, par exemple `{"13":"23","5V":"VIN"}`. Les broches non remappées conservent leur nom et doivent se résoudre sur la nouvelle carte. La validation s’effectue sur le rendu réel de la nouvelle carte avant application ; un échec conserve l’ancienne carte et ses fils. L’application recrée les moteurs et attend le montage du bon type de carte, même si son ID reste identique.

L’ID, le groupe de sources, les fichiers et les composants sont conservés. Les anciennes options de compilation propres à la carte sont réinitialisées ; le code doit être adapté explicitement si l’architecture ou le langage change. Aucune nouvelle conversation n’est nécessaire. `create_project` accepte aussi les cartes non AVR du catalogue et reste réservé aux espaces vides pour préserver les projets existants. Les cartes enregistrées par un overlay sont reconnues à partir du registre du navigateur connecté.

Le contexte initial de chaque tour contient désormais le projet, les chemins des sources, les broches réellement montées, les cartes proposées par l’éditeur et les capacités d’exécution. `get_project` sert à rafraîchir cet état après des changements. Pour un nouveau composant, `get_reference(section="overview")` fournit ensemble les broches réelles, les valeurs par défaut, les propriétés et leurs options, puis les informations de bibliothèque disponibles. Les avertissements du catalogue indiquant des pins non extraites sont retirés quand ces pins ont été résolues dans l’éditeur. Le prompt demande de passer à l’édition dès que ces informations suffisent ; les exemples et détails de protocoles restent consultables si nécessaires.

Le lancement utilise le même Run que l’éditeur pour toutes les familles de cartes et tous les modes de langage pris en charge par l’installation. L’agent conserve les contrôles d’accès et les besoins de compilation, firmware et moteur du Run manuel. Une carte proposée dans le catalogue ne garantit pas que son moteur backend soit installé.

## Démarrage et observation des moteurs

`run_project` vérifie le circuit puis appelle le parcours Run existant : compilation Arduino/ESP-IDF, chargement MicroPython ou lancement Python/Linux selon le projet. Le moniteur série de la carte est vidé avant le nouveau Run afin que l’observation ne reprenne pas une sortie d’une exécution précédente.

- AVR/Pico et autres moteurs locaux : `running` nécessite la confirmation du moteur. Un moteur ESP32 exécuté dans le navigateur peut aussi être confirmé par une avancée de son horloge, mesurée pendant cette exécution.
- ESP32/STM32 backend : l’ouverture du WebSocket reste `booting`. Un événement du moteur confirme le démarrage ; un refus, crash ou échec réseau remonte son diagnostic.
- Raspberry Pi Linux : l’état reste `booting` jusqu’au shell, à l’envoi des fichiers et à l’envoi de la commande du projet. Cette confirmation de démarrage reste distincte du résultat fonctionnel du programme.
- Python instantané : la fin du programme donne `completed`, même si le programme finit avant l’échantillonnage du drapeau d’activité. Les erreurs du programme sont conservées.

Le résultat comprend `state`, `confirmed`, la carte, le mode de langage, `compiled`, `firmware_loaded` et les diagnostics. MicroPython chargé n’est pas présenté comme une compilation Arduino réussie. Après une courte attente, un démarrage long retourne `starting`/`booting`, `confirmed=false` et une consigne d’observation. L’agent appelle alors `observe_project(duration_ms=15000)` sans relancer la compilation. Un démarrage sans confirmation au bout de deux minutes donne `startup_timeout` ; le temps de compilation reste soumis à la limite configurée du tour.

L’arrêt invalide les accusés de l’ancienne exécution et empêche une compilation tardive de laisser la carte active. Les événements de sockets remplacés sont ignorés. L’interface conserve les états de démarrage dans les étapes, après le retour de l’outil.

## Installation locale

Installer OpenCode 1.19.3 sur la machine du backend et le rendre disponible sur `PATH`, ou renseigner `VELXIO_OPENCODE_BIN`. Les dépendances Python sont celles de `backend/requirements.txt` ; aucune bibliothèque de boucle LLM supplémentaire n’est ajoutée.

Le backend se lance comme auparavant :

```sh
cd backend
uvicorn app.main:app --host 127.0.0.1 --port 8001
```

Puis, dans le dossier `frontend`, installer les dépendances et lancer `npm run dev`. Les cores et bibliothèques de compilation restent ceux de l’installation Velxio existante.

Variables facultatives :

| Variable | Valeur / rôle |
| --- | --- |
| `VELXIO_AGENT_ENABLED` | `0` désactive le lancement de nouveaux tours ; activé par défaut si le binaire est présent |
| `VELXIO_OPENCODE_BIN` | Chemin du binaire ; `opencode` par défaut |
| `VELXIO_AGENT_DATA` | Stockage privé ; `~/.local/share/velxio/agent` par défaut |
| `VELXIO_AGENT_ALLOW_ANONYMOUS` | `1` autorise une installation privée sans comptes derrière un proxy ; les accès directs en boucle locale sont déjà autorisés |
| `VELXIO_AGENT_CALLBACK_URL` | URL interne de l’endpoint MCP ; déduite du port FastAPI par défaut |
| `VITE_CONNECTABLE_AGENT` | `true` permet de monter ce panneau dans un build privé ; les builds OSS l’affichent par défaut |

Un compte authentifié utilise les hooks d’identité existants. Le mode anonyme repose sur un cookie privé aléatoire et isole les conversations et les profils. Les réglages, clés et dossiers d’OpenCode sont séparés pour chaque conversation/propriétaire. Les clés locales sont dans un fichier de permissions `0600`, hors projet ; ce MVP ne constitue pas un service public avec isolation OS ou coffre de secrets chiffré.

## Image Docker facultative

```sh
docker compose -f docker-compose.yml -f docker-compose.agent.yml up --build
```

Cette variante vise une installation privée mono-utilisateur. Elle installe OpenCode 1.19.3 avec vérification SHA-256 sur amd64/arm64 et conserve sa licence. Elle stocke les données de l’agent dans le volume `/app/data/agent`. Les prérequis QEMU et toolchains du Dockerfile existant restent nécessaires. Les configurations nginx du dépôt relaient les événements SSE sans buffering.

## Périmètre de cette première version

- URL et modèle personnalisables via une API compatible Chat Completions, test réel d’appel d’outil et sauvegarde des paramètres sans réexposer la clé.
- Harness OpenCode géré automatiquement et démarré au premier message ; conversation en streaming, limites d’étapes et interruption.
- Projet ouvert implicite, fichiers ordinaires, snapshots versionnés, édition du circuit via outils validés et consultation du catalogue existant.
- Création d’un starter pour une carte du catalogue ou du registre connecté si l’espace est vide ; lancement via les moteurs et modes de langage existants, puis lecture de l’état réel, de la série et des diagnostics.
- Préservation de l’identité du projet sauvegardé lors des éditions ; refus des éditions concurrentes et des commandes provenant d’un autre onglet.
- Les captures d’écran, le changement de harness, ACP et le connecteur de fichiers vers une machine distante restent des étapes ultérieures du plan.

Le bouton Run et l’agent passent par le même code de vérification/compilation/lancement. Un démarrage est confirmé par le moteur ou son accusé backend. Le navigateur doit rester connecté ; une compilation réussie n’est pas présentée comme une validation fonctionnelle.

## Vérifications

```sh
PYTHONPATH=backend python -m unittest discover -s test/backend/unit -p test_agent.py -v
RUN_OPENCODE_TEST=1 PYTHONPATH=backend python -m unittest discover -s test/backend/integration -p test_agent_opencode.py -v
cd frontend
npx vitest run src/__tests__/agent-events.test.ts src/__tests__/agent-circuit.test.ts src/__tests__/agent-browser-bridge.test.ts src/__tests__/pin-position-rotation.test.ts src/__tests__/vlx-export-command.test.ts --maxWorkers=1
npx vitest run src/__tests__/agent-execution.test.ts src/__tests__/esp32-integration.test.ts src/__tests__/esp32-dht22-flow.test.ts src/__tests__/raspberry-pi3-bridge-uart-tx.test.ts --maxWorkers=1
```

Le test d’intégration lance le vrai OpenCode, un serveur de modèle déterministe local et le véritable endpoint MCP. Il vérifie une écriture de fichier, un lancement et une observation. Le navigateur y est un double contrôlé : ce test seul ne prouve pas une compilation réelle ou un résultat électronique. Les tests frontend vérifient séparément les conflits, la déduplication, l’accusé du moteur et l’arrêt.

### Test navigateur avec compilation réelle

Avec le backend, le serveur de développement frontend et la toolchain AVR disponibles, démarrer le modèle de test dans un terminal :

```sh
PYTHONPATH=backend python test/backend/integration/test_agent_opencode.py --serve-model --circuit --thinking --swap-board
```

La commande affiche l’URL à placer dans `AGENT_TEST_MODEL_URL`. Avec Playwright et Chromium installés dans l’environnement de test :

```sh
AGENT_TEST_MODEL_URL=http://127.0.0.1:PORT/v1 AGENT_TEST_CIRCUIT=1 AGENT_TEST_SWAP=1 node scripts/test-agent-browser.mjs
```

`PLAYWRIGHT_MODULE` et `CHROMIUM_PATH` peuvent désigner une installation de test existante ; `VELXIO_TEST_URL` vaut `http://127.0.0.1:5181` par défaut. Le script ouvre un contexte navigateur neuf, configure le modèle, envoie une demande dans le chat et vérifie le moteur AVR, la LED et la sortie série. Le scénario refuse d’abord une pin inexistante, puis reconnecte le fil au pin 12. Il vérifie aussi les étapes après rechargement, le thinking au clavier, le thème clair, les traductions françaises et le mobile. Il écrit des captures et les résultats dans `/tmp/velxio-agent-ui-*`. Relancer la fixture pour chaque nouveau parcours complet.

Vérifié le 3 novembre 2026 : vrai OpenCode 1.19.3, Arduino CLI 1.5.1 et core AVR 1.8.6, compilation d’un sketch Uno de 1678 octets, démarrage du moteur dans Chromium et lecture de `42` sur la série par l’outil d’observation. Le modèle était le serveur déterministe de test ; compilateur, firmware et simulateur étaient réels. Aucun message d’erreur JavaScript ni conflit dans ce parcours.

Après les corrections d’interface et de câblage, 22 tests backend et 30 tests frontend ciblés réussissent, ainsi que l’intégration réelle OpenCode. La connexion du pin 12, la LED allumée, la série `42`, le refus d’une pin invalide et la restauration des neuf étapes ont été vérifiés dans Chromium, sans erreur JavaScript. Le parcours étendu vérifie aussi Uno → ESP32 → Uno avec conservation de l’ID et du groupe de sources, la référence LED complète en une lecture et la liste des cartes réellement proposées par le navigateur. Le firmware Uno de 1 962 octets est réel ; le dernier passage bénéficie du cache de compilation. Le modèle déterministe valide le contrat des outils, sans mesurer le nombre de lectures que chaque LLM choisira de faire.

Le build `npm run build:docker` a également réussi. La comparaison TypeScript de ces corrections avec `HEAD` compte 356 diagnostics avant et après, sans nouveau diagnostic ; le contrôle TypeScript global du dépôt reste en échec sur ses problèmes préexistants. Le [rapport d’audit et de correction](agent-audit-corrections.md) détaille les causes, les garanties et les limites vérifiées.

Le [plan d’architecture](architecture-agent-connectable.md) décrit la cible plus large et ses étapes suivantes.

### Vérification de l’extension d’exécution — 4 novembre 2026

22 tests backend, l’intégration réelle OpenCode et 106 tests frontend ciblés passent. Les messages de WebSocket contrôlés couvrent ESP32/STM32 (connexion insuffisante, accusé moteur, refus, crash), Linux en attente, fin d’un script Python, expiration, accès refusé et arrêt. La progression des horloges et le rejet des événements d’une ancienne exécution sont vérifiés.

Dans Chromium, un vrai Pico RP2040 a été créé par remplacement de l’Uno dans le chat, placé en MicroPython et chargé avec le firmware fourni par Velxio. Le programme écrit par l’agent allume la LED câblée sur GP12 et produit `42` sur la série ; Run et Observe retournent `running`, `confirmed=true`. L’AVR est également rejoué en régression. Le modèle reste la fixture déterministe ; firmware et simulateur sont réels. Les succès QEMU ESP32/STM32/Linux sont couverts par des messages contrôlés, leurs moteurs n’étant pas installés dans cet environnement.

Pour rejouer le Pico, lancer la fixture avec `--serve-model --circuit --thinking --pico`, puis `AGENT_TEST_MODEL_URL=http://127.0.0.1:PORT/v1 AGENT_TEST_CIRCUIT=1 AGENT_TEST_PICO=1 node scripts/test-agent-browser.mjs`.

### Évaluation backend avec un modèle local réel

`scripts/test-agent-backend-local.py` teste LED/Uno, servo à 45°/Nano et e-paper/ESP32 avec le véritable OpenCode, le modèle configuré et les outils MCP. Chromium n'est pas nécessaire. Le transport éditeur est remplacé uniquement dans ce script par un stockage de projet isolé : validation des broches réelles (jsdom pour les éléments Wokwi, catalogue pour ESP32/e-paper), résolution des alias par le même code que l'éditeur et compilation via les routes backend de production. Aucun moteur électronique n'est simulé par cet adaptateur : `compiled` confirme un build, jamais un démarrage ou un résultat fonctionnel.

Préparer un fichier privé de connexion au format `ConnectionSettings` (`base_url`, `model`, `api_key`), puis fournir des répertoires Arduino séparés contenant les cores et bibliothèques nécessaires :

```sh
AGENT_MODEL_CONFIG=/chemin/prive/connection.json \
AGENT_TEST_ARTIFACTS=/tmp/velxio-model-evaluation \
ARDUINO_DIRECTORIES_DATA=/chemin/toolchain/data \
ARDUINO_DIRECTORIES_DOWNLOADS=/chemin/toolchain/downloads \
ARDUINO_DIRECTORIES_USER=/chemin/toolchain/user \
PYTHONPATH=backend python scripts/test-agent-backend-local.py
```

Prérequis : OpenCode sur le PATH, dépendances Python du backend, `frontend/node_modules`, Arduino CLI, cores AVR et ESP32, bibliothèques Servo, GxEPD2, Adafruit GFX Library et Adafruit BusIO. `AGENT_TEST_CASES=blink,servo-nano,eink-esp32` permet de sélectionner les cas ; `AGENT_TEST_TIMEOUT` règle la durée maximale d'un tour en secondes.

Chaque cas démarre dans une conversation et un espace de travail neufs. Le script conserve projet `.vlx`, sources, diagnostics, firmware, appels d'outils et réponse du modèle. Une seconde compilation contourne le cache des réponses et contrôle les mêmes sources et la même cible. Les réglages avec la clé restent dans le sous-répertoire privé ; les rapports publics masquent cette clé. Cette série ne vérifie ni géométrie des fils dans le navigateur, ni clignotement réel, ni angle mesuré, ni pixels affichés.

Le contrat agent fournit maintenant `metadataId` dans les résultats de recherche et un `instance_template` complet dans la référence du composant. Les identifiants `component:led` servent aux références, tandis que le projet utilise `metadataId: "led"`. La référence expose aussi `example_references` pour retrouver le vrai code d'initialisation d'une bibliothèque. Lorsqu'une recherche composée ne trouve rien, les mots sont essayés séparément et `query_used` indique le terme effectivement retenu ; `next_offset` indique explicitement la page suivante. Ces enrichissements sont limités aux outils de l'agent et conservent le contrat du serveur MCP compact autonome.

Le [rapport Qwen local](agent-local-model-validation.md) détaille les trois builds réels, les reprises, la comparaison des firmwares et les limites de la vérification backend.

### Ajouts simples et câblage par lot

Le MCP du chat expose `add_component` avec `component` (clé simple ou ID `component:…`), `instance_id`, `properties`, `x` et `y` optionnels. Le serveur complète les valeurs par défaut, génère un ID disponible et propose une position à côté de la carte. Il préserve les autres composants, les fils et les sources modifiées. La réponse contient le composant enregistré et sa référence complète (broches, attributs, exemples) ; l'agent n'a pas besoin de relire cette référence.

```json
{"component":"led","instance_id":"led1","properties":{"color":"red"}}
```

`connect_pins` accepte désormais `connections`, une liste de 1 à 128 paires `from`/`to`. Les connexions existantes sont conservées ; IDs, normalisation des broches et géométrie sont traités par le pipeline existant. L'ensemble est validé avant application : une broche incorrecte refuse tout le lot. L'erreur contient `connection_index` (à partir de zéro) et la paire concernée lorsque le validateur identifie le fil. L'ancien appel avec une seule paire `from`/`to` reste disponible ; les deux formes ne doivent pas être mélangées.

```json
{"connections":[
  {"from":{"componentId":"board","pinName":"2"},"to":{"componentId":"res1","pinName":"1"}},
  {"from":{"componentId":"res1","pinName":"2"},"to":{"componentId":"led1","pinName":"A"}},
  {"from":{"componentId":"led1","pinName":"C"},"to":{"componentId":"board","pinName":"GND"}}
]}
```

Ce lot relie la LED `led1` et la résistance `res1` déjà ajoutées. `update_circuit` reste disponible pour les modifications avancées, sans être nécessaire aux ajouts courants.

Les références renvoient `examples` avec les IDs réels, titres, cartes cibles, bibliothèques et disponibilité du code. `recommended_example` privilégie une carte correspondante parmi les exemples utilisant le composant ; `adapt_board_pins` signale un exemple écrit pour une autre carte. Cela ne certifie pas une compilation sur la nouvelle cible. Une référence inexistante renvoie des `suggestions` issues du catalogue ; les IDs ne sont jamais fabriqués. L'ancien champ `example_references` reste présent pour compatibilité.
