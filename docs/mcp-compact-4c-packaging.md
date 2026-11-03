# 4c — façade réelle, packaging préparé, aucune opération distante exécutée

Le commit 4b approuvé est `65bd663`. `/mcp` utilise FastMCP streamable HTTP **dans `app.main:app`**, même boucle/processus et même owner de compilation. Les six contrats sont enregistrés directement sur le serveur bas niveau du FastMCP neuf ; aucun import de `app.mcp.server`, serveur SSE historique ou septième outil. Le lifespan démarre le gestionnaire de sessions ; le drain des builds précède la fermeture du propriétaire REST. Un adaptateur est capturé à l'admission de chaque job pour garder l'identité/requête d'origine.

Les données restent sous `/app/data/mcp-compact`, avec espaces par identité issue de `get_current_user_id` (anonyme commun si aucun hook auth). Verrou et quota **globaux 256 MiB**, 64 identités actives au maximum, IDs opaques et primitives no-follow existantes. Pas de nouveau mécanisme d'authentification ou de garantie d'isolation réseau. Le réseau d'exposition doit rester celui approuvé par le manager. Le SDK doit fournir `FastMCP(stateless_http, json_response, streamable_http_path)`, `streamable_http_app()` et `session_manager.run()` ; un ancien SDK incompatible est un blocage, pas une autorisation d'installer.

Catalogue : `backend/app/mcp/compact/catalog.snapshot.json` est produit par l'extracteur AST existant et vérifié au chargement par son fichier `.sha256`. Le fichier `.sha256` contient uniquement le digest hexadécimal brut de 64 caractères suivi d’un saut de ligne, sans nom de fichier : `from_snapshot` lit ce format volontairement ; `sha256sum -c` ne lui est pas applicable. Comparer le digest imprimé par `sha256sum` à cette valeur brute. La génération requiert Node **sur le poste de préparation seulement**, jamais dans le backend déployé. Reproduction depuis le checkout revu :

```sh
node scripts/generate-mcp-compact-catalog.cjs . > /tmp/catalog.snapshot.json
cmp /tmp/catalog.snapshot.json backend/app/mcp/compact/catalog.snapshot.json
sha256sum backend/app/mcp/compact/catalog.snapshot.json
python3 -m unittest discover -s test/backend/unit -p 'test_mcp_compact*.py' -q
bash -n packaging/mcp-compact/entrypoint.sh
```

## Préparation manager, après revue seulement

Tous les exemples ci-dessous sont **des commandes futures**, non exécutées ici. Accès uniquement via pve55 puis `pct enter 110` ; cible attendue .75. Aucun accès direct à une autre adresse. Ne pas déduire le nom Docker, son image, ses volumes ou son unité systemd.

```sh
ssh -t root@pve55 'pct enter 110'
# Dans LXC 110 :
umask 077
docker ps --no-trunc
CTR='<nom exact confirmé par inspect>'
docker inspect "$CTR" > container-inspect.json
docker image inspect "$(docker inspect --format '{{.Image}}' "$CTR")" > base-image-inspect.json
systemctl list-units --type=service --all
```

Identifier explicitement l'ancienne unité wrapper Python8002. **Ne pas l'arrêter à ce stade**. Sauvegarder ses fichiers unité/overrides et son état enabled/active avec `systemctl cat/status/is-enabled '<unité exacte>'`. Identifier les mounts réels de `container-inspect.json` et sauvegarder leurs données, notamment `/app/data`, les sources effectives, `/app/entrypoint.sh` et `/etc/nginx/conf.d/default.conf`, avant toute copie/cutover. Arrêter les écritures pour une sauvegarde cohérente ; aucune purge ni recréation de volume.

Sur le poste manager disposant du checkout revu, collecter les préimages depuis le conteneur (transférer les JSON via pve55/pct si le checkout n'est pas dans LXC). Exemple dans LXC si les specs revues y sont disponibles :

```sh
docker exec "$CTR" python3 -c 'import hashlib,json,sys; from pathlib import Path; paths=set(json.loads(sys.argv[1]))|{"/app/entrypoint.sh","/etc/nginx/conf.d/default.conf"}; print(json.dumps({p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in sorted(paths)},sort_keys=True,indent=2))' "$(cat packaging/mcp-compact/reviewed-base.json)" > base-preimages.json
python3 packaging/mcp-compact/prepare.py --inspect container-inspect.json --preimages base-preimages.json --output /tmp/mcp-compact-reviewed-context --image velxio:compact-reviewed
```

La préparation **refuse** une source backend ou un template différent de la base source approuvée `186bea9`. Cette exigence évite d'écraser un correctif compilateur/e-ink local : en cas d'écart, exporter les fichiers réels, comparer et porter les changements dans un nouveau jalon revu. Ne pas remplacer les hashes pour contourner le refus. Le nginx UI est seulement hashé/vérifié, jamais remplacé. Les mounts qui masquent l'overlay sont également refusés. Un montage non représenté autre qu'un volume nommé est bloqué, pas deviné. `create.json` conserve `HostConfig` et matérialise par leur nom inspecté les volumes anonymes qui seraient sinon recréés à vide, donc les bindings IP/ports, volumes, restart policy et limites inspectés ; la configuration de démarrage est remplacée par l'entrypoint sans installation. Relire `create.json` et `manifest.json` intégralement, y compris les mounts hérités et champs réseau.

```sh
BASE_IMAGE=$(python3 -c 'import json; print(json.load(open("/tmp/mcp-compact-reviewed-context/manifest.json"))["base_image"])')
docker image inspect "$BASE_IMAGE"
docker build --pull=false --network=none --build-arg BASE_IMAGE="$BASE_IMAGE" -t velxio:compact-reviewed /tmp/mcp-compact-reviewed-context
# Validation sans lancer l'application ni installer :
docker run --rm --network=none --entrypoint nginx velxio:compact-reviewed -t
docker run --rm --network=none --entrypoint python3 velxio:compact-reviewed -c 'from app.mcp.compact.catalog import Catalog; from app.mcp.compact.checks import CompilerPolicy; import mcp.server.fastmcp; print(Catalog.from_snapshot("/app/app/mcp/compact/catalog.snapshot.json").revision); print(CompilerPolicy("/opt/velxio-mcp-source").prefix)'
```

L'image dérivée conserve les binaires, UI, simulation e-ink et caches de l'image **locale immuable** inspectée. Aucun rebuild du Dockerfile standalone, téléchargement, pip/npm/apt, configuration Docker ou privilège supplémentaire. Le snapshot minimal de policy est installé sous `/opt/velxio-mcp-source/backend/app/services` : il contient les sources exactes et template, pour éviter l'erreur de layout `/app/app` contre `backend/app`. `compiler_policy_unknown` reste bloquant.

## Cutover et rollback : uniquement après nouvelle autorisation manager

1. Conserver ancien conteneur, image ID, inspect JSON, sources/unité et sauvegardes de tous volumes ; vérifier leurs SHA et restauration possible. Sauvegarder séparément les inventaires existants. Aucune commande `docker rm -v`.
2. Vérifier qu'aucune compilation n'est en cours. Arrêter **l'unité wrapper exacte identifiée** ; la désactiver seulement au cutover autorisé pour éviter un retour de Python8002. Noter son état antérieur pour rollback. Aucun superviseur supposé.
3. Arrêter gracieusement l'ancien conteneur (`docker stop --time -1 "$CTR"`), le renommer en nom de backup validé ; ne pas le supprimer. Un SIGKILL externe ne permet pas de garantir le drain.
4. Créer le remplacement avec le JSON revu via l'API Docker locale, qui conserve les options inspectées :

```sh
API_VERSION=$(docker version --format '{{.Server.APIVersion}}')
# Nom validé, sans espaces ni caractères de query string :
NEW_NAME='<nom original validé>'
curl --fail --unix-socket /var/run/docker.sock -H 'Content-Type: application/json' --data-binary @/tmp/mcp-compact-reviewed-context/create.json "http://localhost/v$API_VERSION/containers/create?name=$NEW_NAME"
docker start "$NEW_NAME"
docker logs "$NEW_NAME"
```

Exiger le PID unique uvicorn8001, nginx80+8002, `ESP32 capability blockers=[]`, nginx `-t` valide et aucun setup/core update/install au démarrage. Le port80 garde son bloc UI original. Le nouveau serveur8002 ne proxy que `/mcp`, buffering/cache désactivés. L'ancien wrapper reste arrêté.

Rollback si validation échoue : arrêter gracieusement le nouveau conteneur, le renommer pour diagnostic, redonner à l'ancien son nom et le redémarrer avec sa configuration inchangée ; rétablir exactement l'état enabled/active antérieur du wrapper. Attention : **l'ancien entrypoint peut installer/télécharger au redémarrage** ; si cette politique est interdite, conserver les services arrêtés et demander une procédure rollback source sans installation, ne pas relancer aveuglément. Restaurer les données seulement depuis backup cohérent et après analyse des écritures nouvelles, jamais automatiquement.

## Inventaires réels avant le premier save/check/build

Le catalogue ne prouve aucune installation. Dans le nouveau conteneur, déterminer les racines SDK/core sélectionnées par les services existants et les trois caches réels, sans installer ni scanner le réseau. Exemple de lecture du service :

```sh
docker exec "$NEW_NAME" python3 -c 'from app.services.espidf_compiler import espidf_compiler as s; t=s._idf_target("esp32:esp32:esp32"); a=s._arduino_supports_target(t); v=s._use_idf5(t,a); print("idf",s._idf_root(v)); print("arduino",s._arduino_path_for(v)); print("libraries",s._find_arduino_libraries_dir())'
```

Exécuter la routine avec **ces chemins constatés**, dans l'environnement IDF déjà installé. Le manager remplace explicitement les placeholders suivants ; toute absence est un blocage :

```sh
docker exec "$NEW_NAME" bash -lc '. "<racine IDF constatée>/export.sh" && PYTHONPATH=/app python3 /app/mcp-compact-scripts/mcp-compact-inventory.py --output /app/data/mcp-compact-inventory --idf "<racine IDF constatée>" --arduino "<racine Arduino-as-IDF constatée>" --executable "gcc=<chemin absolu GCC ESP32 sélectionné>" --executable "cmake=<chemin absolu cmake sélectionné>" --executable "ninja=<chemin absolu ninja sélectionné>" --executable "python=<chemin absolu Python IDF sélectionné>" --library "GxEPD2=<cache absolu GxEPD2>" --library "Adafruit GFX Library=<cache absolu GFX>" --library "Adafruit BusIO=<cache absolu BusIO>"'
```

Ajouter `--managed 'vendor/name=<cache absolu vérifié>'` uniquement si un composant managé est réellement requis et disponible. Déterminer les exécutables avec `command -v` dans cet environnement et comparer aux commandes/environnement effectifs du service. Les fichiers gcc/cmake/ninja/python sont également hashés (ceci ne ferme pas leurs bibliothèques dynamiques/transitives). La routine n'appelle aucun SDK/CLI, install ou download : elle lit/hash les fichiers et écrit les preuves. Les arbres, noms et versions de ces trois libs sont vérifiés ; pas de fermeture transitive complète revendiquée. Les sources CMake/scripts utilisateur restent interdits. Pour le projet ESP32 e-paper, **déclarer les trois bibliothèques** dans le snapshot ; les exemples historiques n'en déclarent parfois que deux. Ne pas élargir silencieusement le scope de résolution.

L'inventaire doit être créé avant le premier appel de persistance/check/build : les objets d'inventaire sont capturés par identité et les preuves sont revérifiées à chaque check/build. Un inventaire absent permet save/check partiel mais refuse build. Après changement de liste d'inventaire, drain/redémarrage sans installation avant nouvel essai.

## Preuves de validation à rendre

- Sur un environnement **ayant déjà** les dépendances : `python3 -m unittest discover -s test/backend/unit -p 'test_mcp_compact_facade.py' -q`. Le test ASGI parle réellement JSON-RPC HTTP au SDK, initialise, liste exactement six outils et recherche. Les autres tests sont statiques/fixtures contrôlées ; aucune compilation réelle.
- Depuis le client autorisé : `POST /mcp` avec `Accept: application/json, text/event-stream`, `initialize` protocole `2025-03-26`, puis `notifications/initialized`, `tools/list`, `tools/call`. URL manager attendue : `http://<adresse .75 confirmée>:8002/mcp`. Aucun `/sse` historique.
- Appeler save_project sur un `.vlx` natif ESP32 e-paper relu (options/panelKind/SPIFFS conservés), retenir `project_id` et version exacte ; check_project, lire entièrement le rapport par read_artifact et vérifier son SHA256 ; exiger structure valide, inconnues explicitement documentées.
- build_project start sur cette version/carte, status jusqu'au terminal ; exiger **test_only:false**, PID propriétaire, admission unique scope/priorité, zéro acquisition automatique, provenance SDK/libs/catalogue et limites de reproductibilité/cache partagé off. Lire firmware base64 par tranches ≤12 KiB via read_artifact, décoder et vérifier taille/SHA, lire logs et diagnostics sourcés ; aucune base64 firmware dans la réponse build.
- Vérifier annulation/drain et UI/e-paper inchangés. Ensuite seulement : nouveau test Qwen sur cette façade. Aucun de ces résultats réels n'est annoncé acquis par 4c.
