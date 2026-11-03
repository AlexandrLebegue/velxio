# 4b — procédure manager ultérieure, non exécutée

État livré : hook REST propriétaire dans les sources, **voie ESP32/template revu disponible sous preuves locales, aucun vrai build effectué**. Aucun déploiement, backup distant ou test dans LXC n'a été effectué. La destination indiquée par le manager est LXC **110**, adresse attendue **.75**, via l'hôte **pve55**. Utiliser `pct exec/push` par cet hôte ; ne déduire aucune autre adresse. Aucun accès direct à une adresse de VM/conteneur n'est nécessaire.

Les commandes ci-dessous sont réservées à l'étape future explicitement pilotée par le manager. Elles ne doivent pas être interprétées comme déjà faites. L'utilisateur doit d'abord revoir/committer le 4b ; le commit 3c `de9dd77` ne contient pas ce hook.

## 1. Identification et préconditions, depuis le poste manager

```sh
ssh root@pve55 'pct status 110; pct config 110; pct exec 110 -- hostname; pct exec 110 -- ip -4 -o addr show scope global'
ssh root@pve55 'pct exec 110 -- sh -lc '\''ps -eo pid,args | head -60; command -v python3; command -v docker || true; for d in /app /opt/velxio /srv/velxio; do test ! -f "$d/backend/app/api/routes/compile.py" || printf "%s\n" "$d"; done'\'''
```

Conserver sorties/PID/commande et confirmer l'adresse .75, le propriétaire du process REST, le nombre de workers et le vrai répertoire source. **Ne pas inventer le chemin ou le nom du conteneur.** Si le code tourne dans Docker, déterminer d'abord conteneur/montages/processus via `docker ps`/`docker inspect` ; arrêter la procédure de copie ci-dessous jusqu'à validation du mapping. Si plusieurs workers partagent les répertoires ESP-IDF, le propriétaire unique n'est pas établi : ne pas lancer de build.

## 2. Archive source exacte revue, aucune installation

Sur le poste disposant du worktree isolé (pas l'ancien dépôt) :

```sh
cd /home/dev/projects/velxio-mcp-compact
REVIEWED_COMMIT='<hash du commit 4b après approbation>'
git cat-file -e "$REVIEWED_COMMIT:backend/app/mcp/compact/offline_owner.py"
git archive --format=tar "$REVIEWED_COMMIT" -- backend/app/mcp/compact backend/app/api/routes/compile.py backend/app/services/arduino_cli.py backend/app/services/espidf_compiler.py backend/app/services/espidf_offline.py scripts/generate-mcp-compact-catalog.cjs test/backend/unit/test_mcp_compact_catalog.py test/backend/unit/test_mcp_compact_projects.py test/backend/unit/test_mcp_compact_checks.py test/backend/unit/test_mcp_compact_builds.py test/backend/unit/test_mcp_compact_offline_owner.py test/backend/unit/test_mcp_compact_espidf_offline.py > /tmp/velxio-4b-source.tar
sha256sum /tmp/velxio-4b-source.tar
scp /tmp/velxio-4b-source.tar root@pve55:/root/velxio-4b-source.tar
ssh root@pve55 'pct push 110 /root/velxio-4b-source.tar /root/velxio-4b-source.tar'
```

Le `git cat-file` doit réussir sur le commit revu, pas être remplacé par `HEAD` sans vérification. Aucun `npm install`, `pip install`, core/library install, image build ou téléchargement de toolchain.

## 3. Backup avant copie, uniquement après chemin confirmé

Ouvrir la console de ce LXC depuis pve55 :

```sh
ssh -t root@pve55 'pct enter 110'
```

Dans LXC **110**, définir **manuellement** le chemin réel identifié à l'étape 1, puis :

```sh
set -eu
APP_DIR='<répertoire réel validé contenant backend/ et frontend/>'
test -f "$APP_DIR/backend/app/api/routes/compile.py"
BACKUP_DIR="/root/velxio-before-4b-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -m 700 "$BACKUP_DIR"
tar -C "$APP_DIR" -cpf "$BACKUP_DIR/source.tar" backend/app/mcp backend/app/api/routes/compile.py backend/app/services/arduino_cli.py backend/app/services/espidf_compiler.py
if test -d /app/data; then tar -C /app -cpf "$BACKUP_DIR/app-data.tar" data; fi
sha256sum "$BACKUP_DIR"/*.tar > "$BACKUP_DIR/SHA256SUMS"
sha256sum -c "$BACKUP_DIR/SHA256SUMS"
tar -tf /root/velxio-4b-source.tar > "$BACKUP_DIR/incoming-files.txt"
cat "$BACKUP_DIR/incoming-files.txt"
```

Vérifier l'espace disponible et le contenu avant toute extraction. Si l'ancien répertoire MCP n'existe pas, adapter **explicitement** la liste de backup après revue, pas ignorer une erreur tar. Sauvegarder séparément les volumes réels identifiés si `/app/data` est un montage d'un conteneur Docker plutôt que celui du LXC. Aucun rollback/purge automatique.

## 4. Copie et vérification locale sans vrai build

Toujours dans le LXC, après backup validé et autorisation de copie :

```sh
tar -C "$APP_DIR" -xpf /root/velxio-4b-source.tar
cd "$APP_DIR"
python3 --version
node --version
node -e 'for (const n of ["@babel/parser","@babel/core","@babel/traverse","@babel/plugin-transform-typescript","ajv"]) console.log(n,require.resolve(n))'
python3 -m unittest discover -s test/backend/unit -p 'test_mcp_compact*.py' -q
```

Toutes les compilations de ces tests sont **monkeypatchées/factices**, explicitement marquées comme telles. Une dépendance locale absente ou un écart d'AST Python est un blocage à rapporter ; ne pas installer ni ajouter aveuglément une empreinte CompilerPolicy. Ne pas lancer un processus MCP autonome pour compiler. Ne pas créer un second `BuildQueue` pour contourner l'admission du REST existant.

Le chargement du hook dans le vrai worker REST nécessite ensuite une opération de redémarrage **spécifique à la supervision constatée**, à approuver séparément après backup. La commande exacte de service/Docker n'est pas connue ici et ne doit pas être inventée. Dans ses logs, exiger le message `Compact offline REST owner registered pid=...; ESP32 capability blockers=[]; OS network isolation not provided`, avec le PID du worker REST réellement identifié. Ce message prouve l'enregistrement, **pas** un build offline réussi. Aucune nouvelle route ne permet de binder depuis l'extérieur ; l'appel interne doit provenir de l'application/boucle REST active.

## 5. Preuves exigées avant toute étape de compilation réelle

- Commit/archive/SHA et backups vérifiés, cible LXC 110/.75 confirmée via pve55, fichiers/PID/loop du vrai owner et une seule admission sur la file partagée.
- Résultats de tests avec nombre/durée, mention explicite des services monkeypatchés, absence de vraie compilation et d'installation ; régressions existantes conservées.
- Inventaires locaux à hashes vérifiés pour libs/toolchain et, pour Arduino, fichiers `platform.txt`/`boards.txt` et version du core ; ne pas confondre ces preuves avec une fermeture transitive complète.
- ESP32 seulement : refus attendu si template modifié, preuve SDK manquante/modifiée, cache dépendance absent, primitives CMake non prises en charge ou SPIFFS sans outil local. Hors ESP32 : `unsupported`. Pas de fallback ou installation.
- Fournir le manifest ToolchainInventory dont `members` épingle au minimum `tools/idf.py`, `tools/cmake/project.cmake` du SDK effectivement sélectionné, plus `CMakeLists.txt` du composant Arduino si nécessaire. `idf_root`/`arduino_root` sont absolus et doivent correspondre aux services réels. Les hashes sont recalculés avant exécution.
- Chaque librairie déclarée conserve sa preuve `library.properties` et ajoute `source_root` absolu + `tree_sha256 = digest(tree_manifest(source_root))`. Les composants managés déjà présents sont listés dans `managed_components` avec `name`, `source_root`, `tree_sha256`. Une source détectée demandant un composant absent échoue avant CMake ; une dépendance transitive non détectée peut encore échouer à CMake, sans acquisition automatique. Ne pas prétendre fermeture transitive complète.
- Après **nouvelle autorisation** : instrumenter dans le vrai processus/boucle REST les fonctions sync/download/install/warmup/heal en échec immédiat, appeler `bind_compact_offline_owner(request,user)` depuis ce propriétaire, puis BuildService avec inventaires `test_only:false` et snapshot/carte exacts. Ne pas importer un second owner dans un script extérieur pour compiler. Aucune route d'accès externe n'est ajoutée à ce jalon ; le harness propriétaire reste à intégrer/revoir avant cette preuve.
- Conserver le journal du vrai owner PID/boucle, une seule acquisition/libération `build_queue.lane_for`, scope/priorité, version/catalogue/manifest SHA, commandes CMake/Ninja et leur environnement (`IDF_COMPONENT_MANAGER=0`, `CCACHE_DISABLE=1`, fetch déconnecté), zéro appel interdit, ID/statut/diagnostics, hash/taille/lecture bornée des artefacts et drain sur annulation. Un build réussi sans ces traces n'est pas une preuve suffisante.
- Fait fourni par le manager, non retesté ici : FastAPI 0.115.0 supporte APIRouter lifespan ; `/opt/esp-idf/tools/idf.py` et `/usr/bin/unshare` existent mais `unshare -n -- true` est refusé. Aucune commande unshare/CAP/privileged/configuration Docker à ajouter. Aucune isolation réseau OS n'est revendiquée. Les SDK/outils locaux approuvés restent une frontière de confiance.

### Commande de preuve locale (lecture seule, dans le répertoire APP_DIR validé)

Après revue/backup/copie, dans la console LXC obtenue via `ssh -t root@pve55 'pct enter 110'`, utiliser les racines **effectivement sélectionnées**, sans installer ce qui manque :

```sh
cd "$APP_DIR"
PYTHONPATH=backend python3 - /opt/esp-idf <<'PY'
import hashlib, json, sys
from pathlib import Path
from app.services.espidf_offline import approved_template, digest, tree_manifest
sdk = Path(sys.argv[1])
members = []
for name in ('tools/idf.py', 'tools/cmake/project.cmake'):
    path = sdk / name
    members.append({'path': name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
print(json.dumps({'inventory_root': str(sdk), 'idf_root': str(sdk), 'members': members}, indent=2))
print('template_approved', approved_template(Path('backend/app/services/esp-idf-template').absolute()))
PY
```

Le chemin template correspond exactement à `_TEMPLATE_DIR` dans le service revu ; aucun chemin ne doit être créé pour faire passer cette preuve. La sortie est une aide à l'inventaire, pas un manifest complet signé ni une preuve de toolchain transitive. Aucun build n'est exécuté par cette commande. Pour chaque cache confirmé : `PYTHONPATH=backend python3 -c 'import sys; from app.services.espidf_offline import tree_manifest,digest; print(digest(tree_manifest(sys.argv[1])))' '<racine absolue cache validée>'`. Conserver les sorties avec le manifest final et ses hashes.
