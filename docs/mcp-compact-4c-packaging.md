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

Rollback : utiliser la recette « ancienne image, démarrage sans installation » ci-dessous. **Ne pas redémarrer l'ancien conteneur avec son entrypoint original**. Les données ne sont jamais restaurées automatiquement : conserver les écritures nouvelles et comparer aux backups cohérents avant toute décision de restauration.

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

## Scripts de preuve isolée, aucune action de production

Preuves **rapportées par le manager**, non réexécutées ici : sur 110, vrai SDK installé, test ASGI non ignoré PASS en 0,568 s (`initialize`, six outils, recherche cinq résultats, HTTP200) ; les douze préimages backend/template sont identiques au manifeste revu. Backup annoncé : `/root/velxio-compact-20261103/source-before.tar`, SHA256 `6745443c603c768b33747fecac1addd36928a237ab5ec51230adcbf5eae69749`. Inspect et état enabled/active du wrapper y sont conservés. Ces faits ne constituent pas encore une preuve save/check/build ni un cutover.

Deux scripts nouveaux, à transférer comme **sources** dans l'image de revue ou à monter en lecture seule ; aucune modification de la façade/architecture, aucune copie automatique dans une image de production :

- `scripts/mcp-compact-review-inventory.sh` active seulement le SDK **déjà installé**, appelle la routine d'inventaire existante puis revérifie les preuves avec `LibraryInventory` et `ToolchainInventory`. Il écrit `inventory/inventory.json` et `inventory-proof.json`. stdout est un objet JSON, diagnostics/activation SDK sur stderr. Une preuve existante est conservée et fait refuser la réexécution ; seules des options supplémentaires `--managed name=/cache/absolu` sont acceptées.
- `scripts/mcp-compact-review-smoke.py` démarre le **vrai lifespan de `app.main`**, vérifie le propriétaire actif/genuine/PID/boucle, puis appelle JSON-RPC `/mcp` par ASGI réel : initialize/notification/list/search/save/check/read_artifact. Le `.vlx` natif est fourni par le manager, sans projet ou firmware factice intégré. Le projet relu doit être identique ; projet, rapport et éventuels firmware/logs sont lus par tranches ≤12 KiB et leurs tailles/SHA sont vérifiés. Le build est **désactivé par défaut** ; `--build` l'admet exclusivement via MCP et le propriétaire REST existant, jamais via un compilateur invoqué directement.

Exécuter uniquement dans un **nouveau conteneur de revue sans mounts de production**, sans ports publiés, `--network=none`, avec les SDK/libs déjà dans l'image. `MCP_REVIEW_ISOLATED=1` est une confirmation du manager, pas un mécanisme de sandbox. L'isolation doit venir de la commande Docker effectivement inspectée ; ne pas réutiliser le `HostConfig` de production pour ce test. Racine de preuve sous `/tmp/<nouveau-run>` ou `/review/<nouveau-run>`. Exemple de lancement à adapter après identification des chemins locaux (aucune adresse réseau) :

```sh
REVIEW_IMAGE='<ID sha256 exact de image dérivée isolée>'
REVIEW_SOURCES='<répertoire manager contenant les deux scripts, lecture seule>'
REVIEW_INPUT='<répertoire manager de la copie .vlx relue, lecture seule>'
# Pas de --rm : conserver le conteneur arrêté et ses preuves pour docker cp.
docker run --pull=never --name '<nom de revue unique>' --network=none --entrypoint /bin/bash \
  --mount "type=bind,src=$REVIEW_SOURCES,dst=/review-scripts,readonly" \
  --mount "type=bind,src=$REVIEW_INPUT,dst=/review-input,readonly" \
  --env-file '<fichier env revue explicite, sans secret de production>' \
  "$REVIEW_IMAGE" -c 'bash /review-scripts/mcp-compact-review-inventory.sh && . "$IDF_ROOT/export.sh" >&2 && exec "$IDF_PYTHON" /review-scripts/mcp-compact-review-smoke.py --review-root "$REVIEW_ROOT" --app-root "$REVIEW_APP_ROOT" --source-root "$POLICY_SOURCE_ROOT" --inventory "$REVIEW_ROOT/inventory/inventory.json" --project "$PROJECT_VLX" --board-id "$PROJECT_BOARD_ID"'
```

Le fichier env de revue contient **toutes** les valeurs ci-dessous, constatées dans l'image/environnement IDF par le manager ; aucune racine SDK/lib/exécutable ne doit être devinée. Les noms à gauche sont fixes, les valeurs à droite sont à remplir, pas à utiliser littéralement :

```text
MCP_REVIEW_ISOLATED=1
REVIEW_ROOT=/tmp/<nouveau-run-unique>
REVIEW_APP_ROOT=<répertoire absolu contenant app/>
INVENTORY_SCRIPT=<chemin absolu de mcp-compact-inventory.py existant>
POLICY_SOURCE_ROOT=<snapshot absolu contenant backend/app/services>
IDF_ROOT=<SDK effectivement sélectionné>
ARDUINO_ROOT=<composant Arduino-as-IDF effectivement sélectionné>
GXEPD2_ROOT=<cache réel GxEPD2>
GFX_ROOT=<cache réel Adafruit GFX Library>
BUSIO_ROOT=<cache réel Adafruit BusIO>
GCC_PATH=<GCC ESP32 effectivement sélectionné>
CMAKE_PATH=<cmake effectivement sélectionné>
NINJA_PATH=<ninja effectivement sélectionné>
IDF_PYTHON=<Python IDF effectivement sélectionné>
PROJECT_VLX=/review-input/<copie native relue>.vlx
PROJECT_BOARD_ID=<id exact de carte dans cette copie>
```

Le shell `export.sh` lancé par l'inventaire ne modifie pas l'environnement du shell parent ; la commande ci-dessus active donc aussi le même SDK dans le parent avant `exec` du smoke. Il s'agit d'une activation locale, jamais d'un appel `install.sh` ou d'une réparation. Les hooks de startup de l'image restent du code réel : tout prérequis manquant doit échouer, sans installation. Les scripts ne certifient pas une fermeture transitive du SDK. Un `docker commit` n'inclut pas les volumes : si SDK/libs y résident, fournir une copie de revue locale vérifiée dans l'image isolée, sans installer ni monter le volume de production en écriture.

Après revue du save/check, un **nouveau run isolé** peut ajouter `--build --status-seconds 120 --max-polls 120` à la commande smoke. Utiliser une copie native ESP32 simple ou e-paper relue, avec code source réel et les trois bibliothèques déclarées ; aucun firmware de référence copié en dur. Le résultat doit contenir `test_only:false`. Le délai borne **le polling**, pas la durée totale du compilateur : à expiration, la preuve est publiée avant le drain, puis le vrai lifespan attend la fin du propriétaire sans annuler ou abandonner une compilation partagée. Ne pas appliquer un `timeout`/SIGKILL externe pour fabriquer un succès borné.

stdout du smoke est du **JSON Lines** (avis d'expiration éventuel puis preuve finale), stderr reçoit les sorties SDK/startup ; la preuve finale atomique est `$REVIEW_ROOT/smoke-proof.json` (≤256 KiB). Codes : 0 = scénario terminé ; 1 = échec ; 3 = polling expiré et propriétaire drainé. Une preuve/store existant fait refuser une nouvelle exécution : choisir une nouvelle racine. À quota/erreur, conserver tous fichiers, aucun changement de moteur/purge/fallback. Les fichiers `artifact-a_<id>.bin` contiennent les octets réellement relus, pas leur base64. Les appels MCP ont un délai de 30 s ; une opération Python synchrone peut retarder la prise en compte de ce délai. Le nombre d'admissions/scope détaillé exige toujours les traces du propriétaire existant ; le smoke ne les invente pas.

```sh
docker logs '<nom de revue unique>' > '<preuve stdout et stderr>.log' 2>&1
docker cp '<nom de revue unique>:/tmp/<nouveau-run-unique>' '<destination manager nouvelle>'
# Lire smoke-proof.json et comparer SHA/taille des artefacts copiés.
```

## Rollback : ancienne image + entrypoint sans installation + nginx original

Cette recette **prépare une image de rollback**, sans restaurer l'ancien entrypoint auto-install et sans manipuler les services actuels. Elle remplace la précédente suggestion de redémarrer l'ancien conteneur. Exécution/cutover exclusivement par le manager après backup et autorisation ; aucune commande ci-dessous n'a été exécutée par l'agent.

Sur 110, partir de l'**ID immuable de l'image ancienne enregistré avant overlay**, par exemple celui du docker commit de sauvegarde annoncé par le manager, vérifié dans les preuves. Ne pas prendre l'ID de l'image nouvelle ou un tag mutable par commodité. Le conteneur historique reste arrêté/conservé au cutover, jamais démarré avec son entrypoint original.

```sh
umask 077
OLD_BASE='<ID sha256 immuable image ancienne sauvegardée>'
ROLLBACK_CONTEXT='<nouveau répertoire manager dédié>'
REVIEW_CHECKOUT='<répertoire des sources revues>'
SAVED_INSPECT='<container-inspect.json original sauvegardé>'
PREPARED_CREATE='<create.json 4c revu conservant les volumes existants par nom>'
ROLLBACK_TAG='<tag local rollback sans install choisi manager>'
docker image inspect "$OLD_BASE"
mkdir -m 700 "$ROLLBACK_CONTEXT"
cp "$REVIEW_CHECKOUT/packaging/mcp-compact/entrypoint.sh" "$ROLLBACK_CONTEXT/entrypoint-no-install.sh"
# Lecture pure d'une nouvelle instance éphémère, sans mounts/ports de production,
# sans lancer le CMD/ENTRYPOINT de la base. Aucun compilateur n'est invoqué.
docker run --rm --pull=never --network=none --entrypoint /bin/cat "$OLD_BASE" \
  /etc/nginx/conf.d/default.conf > "$ROLLBACK_CONTEXT/nginx-original.conf"
sha256sum "$ROLLBACK_CONTEXT/nginx-original.conf" "$ROLLBACK_CONTEXT/entrypoint-no-install.sh"
# Comparer nginx-original.conf au SHA sauvegardé de production avant cutover.
cat > "$ROLLBACK_CONTEXT/Dockerfile" <<'DOCKER'
ARG BASE_IMAGE
FROM ${BASE_IMAGE}
USER root
COPY entrypoint-no-install.sh /app/rollback-entrypoint-no-install.sh
COPY nginx-original.conf /etc/nginx/conf.d/default.conf
RUN chmod 0755 /app/rollback-entrypoint-no-install.sh \
 && test ! -e /etc/nginx/conf.d/mcp-compact.conf \
 && nginx -t
ENTRYPOINT ["/app/rollback-entrypoint-no-install.sh"]
CMD []
DOCKER
docker build --pull=false --network=none --build-arg BASE_IMAGE="$OLD_BASE" \
  -t "$ROLLBACK_TAG" "$ROLLBACK_CONTEXT"
ROLLBACK_IMAGE=$(docker image inspect --format '{{.Id}}' "$ROLLBACK_TAG")
docker run --rm --pull=never --network=none --entrypoint nginx "$ROLLBACK_IMAGE" -t
# Validation syntaxique sans démarrage :
docker run --rm --pull=never --network=none --entrypoint /bin/bash "$ROLLBACK_IMAGE" \
  -n /app/rollback-entrypoint-no-install.sh
```

La base doit avoir son nginx original sans fragment MCP8002 ; sinon le `test ! -e` bloque, sans supprimer une configuration inconnue. Le nouvel entrypoint active uniquement le SDK installé puis uvicorn8001/nginx80 avec `wait -n` et arrêt du pair ; il ne lance aucun core/index/library setup. Fournir dans le create env `IDF_PATH` si la racine constatée diffère de la valeur héritée, après revue explicite. Les autres sources/binaires/UI/e-ink de la base ne sont pas remplacés.

Générer un JSON de création de rollback depuis le **Config original sauvegardé** et le **HostConfig déjà préparé/revu** qui conserve aussi les volumes anonymes par leur nom. Ne pas réinventer un `docker run -v` incomplet :

```sh
python3 - "$SAVED_INSPECT" "$PREPARED_CREATE" "$ROLLBACK_IMAGE" "$ROLLBACK_CONTEXT/rollback-create.json" <<'PY'
import copy, json, re, sys
from pathlib import Path
saved, prepared, image, output = sys.argv[1:]
rows = json.loads(Path(saved).read_bytes())
def require(condition, message):
    if not condition:
        raise SystemExit(message)
require(len(rows) == 1, 'Exactly one original inspected container required')
old = rows[0]; ready = json.loads(Path(prepared).read_bytes())
require(re.fullmatch(r'sha256:[0-9a-f]{64}', image), 'Immutable rollback image ID required')
require(old['HostConfig']['NetworkMode'] == ready['HostConfig']['NetworkMode'] == 'bridge', 'Bridge changed')
require(old['HostConfig']['PortBindings'] == ready['HostConfig']['PortBindings'], 'Port bindings changed')
require(not ready['HostConfig'].get('AutoRemove'), 'AutoRemove is incompatible with retained rollback')
require(not ready['HostConfig'].get('VolumesFrom'), 'VolumesFrom needs explicit review')
# Allow ONLY the exact anonymous-volume materialization performed by prepare.py.
expected = copy.deepcopy(old['HostConfig'])
represented = {b.split(':')[1] for b in (expected.get('Binds') or [])}
represented |= {m['Target'] for m in (expected.get('Mounts') or [])}
represented |= set(expected.get('Tmpfs') or {})
for mount in old['Mounts']:
    if mount['Destination'] in represented:
        continue
    require(mount['Type'] == 'volume' and mount.get('Name'), 'Unknown original mount')
    if expected.get('Mounts') is None:
        expected['Mounts'] = []
    expected['Mounts'].append({'Type':'volume', 'Source':mount['Name'],
        'Target':mount['Destination'], 'ReadOnly':not mount['RW'], 'VolumeOptions':{'NoCopy':True}})
require(expected == ready['HostConfig'], 'HostConfig differs beyond reviewed volume materialization')
# Every actual inspected mount must retain its destination/source/access.
bindings = ready['HostConfig'].get('Binds') or []
mounts = ready['HostConfig'].get('Mounts') or []
for mount in old['Mounts']:
    destination = mount['Destination']
    source = mount.get('Name') if mount['Type'] == 'volume' else mount['Source']
    access = 'rw' if mount['RW'] else 'ro'
    via_bind = any(b.split(':')[:2] == [source, destination] and
                   access in (b.split(':', 2)[2].split(',') if b.count(':') >= 2 else ['rw'])
                   for b in bindings)
    via_mount = any(m['Type'] == mount['Type'] and m['Source'] == source and
                    m['Target'] == destination and bool(m.get('ReadOnly', False)) == (not mount['RW'])
                    for m in mounts)
    if not (via_bind or via_mount):
        raise SystemExit('Mount identity/access not preserved; explicit review required: ' + destination)
config = copy.deepcopy(old['Config'])
config.update(Image=image, Entrypoint=['/app/rollback-entrypoint-no-install.sh'], Cmd=[],
              HostConfig=copy.deepcopy(ready['HostConfig']))
with Path(output).open('x') as stream:
    stream.write(json.dumps(config, sort_keys=True, indent=2) + '\n')
print(json.dumps({'image':image, 'ports':config['HostConfig']['PortBindings'],
                  'mounts_preserved':len(old['Mounts']), 'created':False}))
PY
```

Relire le JSON avant toute action. `HostConfig` doit être celui du **même inspect original** ; seul l'ajout revu de noms de volumes anonymes est admis. Les montages tmpfs/options inhabituelles sont bloquants si le générateur ne peut pas en prouver l'identité. Si un mount masque `/app`/l'entrypoint/nginx, arrêter et revoir le mapping : ne pas contourner par une configuration Docker différente.

Seulement au cutover/rollback autorisé, après drain et vérification des backups : arrêter le conteneur de la nouvelle version, le renommer pour diagnostic, conserver l'ancien conteneur sans le démarrer. Libérer le nom original pour la nouvelle instance de rollback, puis :

```sh
# Ces valeurs sont les noms exacts constatés et validés par le manager.
FAILED_CONTAINER='<nom exact nouvelle version à arrêter>'
FAILED_KEEP='<nom backup diagnostic unique>'
ORIGINAL_NAME='<nom de conteneur original valide [A-Za-z0-9][A-Za-z0-9_.-]*>'
docker stop --time -1 "$FAILED_CONTAINER"
docker rename "$FAILED_CONTAINER" "$FAILED_KEEP"
API_VERSION=$(docker version --format '{{.Server.APIVersion}}')
curl --fail --unix-socket /var/run/docker.sock -H 'Content-Type: application/json' \
  --data-binary @"$ROLLBACK_CONTEXT/rollback-create.json" \
  "http://localhost/v$API_VERSION/containers/create?name=$ORIGINAL_NAME"
docker start "$ORIGINAL_NAME"
docker logs "$ORIGINAL_NAME"
docker inspect "$ORIGINAL_NAME" > "$ROLLBACK_CONTEXT/rollback-inspect.json"
```

Comparer les mounts et `HostConfig.PortBindings` au JSON original : `80→3080`, `8002→8002` avec **mêmes HostIp**, mêmes volumes/binds et accès. Nginx original ne sert que son bloc80 : le port8002 reste sans listener tant que le wrapper historique n'a pas été rétabli. Restaurer l'état enabled/active du **wrapper exact sauvegardé** uniquement après vérification de son unité : elle doit viser ce nom de conteneur, et ne pas relancer l'ancien entrypoint ni un setup. Si elle vise l'ancien ID immuable ou comporte des actions non revues, arrêter la procédure et signaler le blocage ; ne pas modifier l'unité hors autorisation. Aucun superviseur supposé. Conserver les données actuelles ; aucune suppression de volume, aucun `docker rm -v`, aucune restauration automatique des snapshots.
