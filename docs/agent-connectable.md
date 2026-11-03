# Agent IA dans l’éditeur

Le bouton **Agent IA**, en bas à droite, ouvre la conversation. Le menu File donne aussi accès au panneau et à ses paramètres. Le moteur utilisé est OpenCode 1.19.3 ; les requêtes au modèle et les clés restent côté serveur.

## Utilisation

1. Ouvrir le projet dans l’éditeur, ou un espace vide pour demander un starter.
2. Ouvrir les paramètres IA et renseigner l’URL de base de l’API compatible Chat Completions, l’identifiant exact du modèle et, si nécessaire, sa clé.
3. Tester la connexion : le test vérifie le streaming et demande un appel d’outil sans effet.
4. Enregistrer, puis demander une modification. Exemple : « Fais clignoter la LED et affiche son état sur le port série. Lance et observe la simulation. »

Le serveur doit pouvoir joindre le LLM. Pour un moteur local, l’URL peut être `http://127.0.0.1:11434/v1`. Dans Docker, cette adresse désigne le conteneur : utiliser le nom du service LLM ou l’adresse réseau de son hôte.

L’agent travaille sur des fichiers ordinaires dans un dossier propre à la conversation. Le manifeste `.velxio.json` associe automatiquement ce dossier à son projet. Le modèle n’envoie ni tableau `files` ni `project_id` pour lancer le projet actif.

Les sources sont appliquées au lancement ou à la fin du tour. Une modification manuelle concurrente est conservée et produit un conflit explicite. Le bouton de téléchargement permet de récupérer le snapshot de l’agent en `.vlx`. « Arrêter » interrompt le tour et empêche une compilation en cours de laisser ensuite une simulation active ; le compilateur déjà admis peut terminer son travail.

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
- Création d’un starter AVR si l’espace est vide ; lancement des cartes Uno, Nano, Mega et ATtiny85 dans le navigateur puis lecture de la série et des diagnostics.
- Préservation de l’identité du projet sauvegardé lors des éditions ; refus des éditions concurrentes et des commandes provenant d’un autre onglet.
- Les autres cartes restent éditables ; leur lancement par l’agent est explicitement indisponible. Les captures d’écran, le changement de harness, ACP et le connecteur de fichiers vers une machine distante restent des étapes ultérieures du plan.

Le bouton Run et l’agent passent par le même code de vérification/compilation/lancement. Un démarrage est confirmé seulement si le moteur AVR indique qu’il tourne. Le navigateur doit rester connecté ; une compilation réussie n’est pas présentée comme une validation fonctionnelle.

## Vérifications

```sh
PYTHONPATH=backend python -m unittest discover -s test/backend/unit -p test_agent.py -v
RUN_OPENCODE_TEST=1 PYTHONPATH=backend python -m unittest discover -s test/backend/integration -p test_agent_opencode.py -v
cd frontend
npx vitest run src/__tests__/agent-browser-bridge.test.ts src/__tests__/vlx-export-command.test.ts --maxWorkers=1
```

Le test d’intégration lance le vrai OpenCode, un serveur de modèle déterministe local et le véritable endpoint MCP. Il vérifie une écriture de fichier, un lancement et une observation. Le navigateur y est un double contrôlé : ce test seul ne prouve pas une compilation réelle ou un résultat électronique. Les tests frontend vérifient séparément les conflits, la déduplication, l’accusé du moteur et l’arrêt.

### Test navigateur avec compilation réelle

Avec le backend, le serveur de développement frontend et la toolchain AVR disponibles, démarrer le modèle de test dans un terminal :

```sh
PYTHONPATH=backend python test/backend/integration/test_agent_opencode.py --serve-model
```

La commande affiche l’URL à placer dans `AGENT_TEST_MODEL_URL`. Avec Playwright et Chromium installés dans l’environnement de test :

```sh
AGENT_TEST_MODEL_URL=http://127.0.0.1:PORT/v1 node scripts/test-agent-browser.mjs
```

`PLAYWRIGHT_MODULE` et `CHROMIUM_PATH` peuvent désigner une installation de test existante ; `VELXIO_TEST_URL` vaut `http://127.0.0.1:5181` par défaut. Le script ouvre un contexte navigateur neuf, configure le modèle, envoie une demande dans le chat et vérifie le moteur AVR et la sortie série. Il écrit une capture et les résultats dans `/tmp/velxio-agent-ui-*`.

Vérifié le 3 novembre 2026 : vrai OpenCode 1.19.3, Arduino CLI 1.5.1 et core AVR 1.8.6, compilation d’un sketch Uno de 1678 octets, démarrage du moteur dans Chromium et lecture de `42` sur la série par l’outil d’observation. Le modèle était le serveur déterministe de test ; compilateur, firmware et simulateur étaient réels. Aucun message d’erreur JavaScript ni conflit dans ce parcours.

Le build `npm run build:docker` a également réussi. La comparaison TypeScript avec les fichiers de `HEAD` compte 357 diagnostics avant ces changements et 356 après, sans nouveau diagnostic ; le contrôle TypeScript global du dépôt reste donc en échec sur ses problèmes préexistants.

Le [plan d’architecture](architecture-agent-connectable.md) décrit la cible plus large et ses étapes suivantes.
