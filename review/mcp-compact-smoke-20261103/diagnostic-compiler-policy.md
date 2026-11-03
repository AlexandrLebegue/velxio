# Run D — diagnostic de `compiler_policy_unknown` (analyse seule)

La politique contient une incompatibilité reproductible entre **Python 3.13 et 3.12** : ses empreintes figées portent sur la représentation textuelle de `ast.dump()`, dont le traitement des listes vides a changé. Elles correspondent au dump par défaut de Python **3.13.5** du poste d'inspection ; le Run D utilise **Python 3.12**. Avec les sources revues identiques, la première empreinte peut donc échouer sans changement du compilateur. Le contrôle concerné est `backend/app/mcp/compact/checks.py:110–117`, avant la lecture du répertoire template.

**Limite de preuve importante :** les fichiers fournis du Run D ne contiennent ni l'exception originale interceptée par `CompilerPolicy`, ni un inventaire des octets de `/opt/velxio-mcp-source`. La divergence du format AST est démontrée localement ; son attribution au premier échec effectif du Run D doit être close par la commande en fin de document. On ne peut pas affirmer, depuis ces seuls exports, qu'aucun fichier du snapshot image n'est également absent ou différent. Aucun accès à l'image, à LXC110 ou à la production n'a été effectué pour cette analyse.

## Chaîne exacte du refus

1. `scripts/mcp-compact-review-smoke.py:148` définit `MCP_COMPACT_SOURCE_ROOT` à partir de `--source-root`, avant l'import de l'application. La preuve `env-d.list` donne `POLICY_SOURCE_ROOT=/opt/velxio-mcp-source`.
2. `backend/app/mcp/compact/facade.py:53` lit cette racine ; `facade.py:93` la transmet à `ProjectChecker`.
3. `checks.py:209` construit `CompilerPolicy(self.source_root)`. `checks.py:211–214` intercepte notamment `OSError`, `ValueError` et `SyntaxError`, **sans conserver leur détail**, puis produit `template_policy_unknown` sur `/fileGroups` et marque `compiler_file_layout` indisponible.
4. `backend/app/mcp/compact/builds.py:201–202` refuse ensuite `compiler_policy_unknown` si ce contrôle est indisponible. Ce refus précède la vérification de l'inventaire toolchain à `builds.py:223–230` et l'exécution du compilateur.

Ainsi `structure_status=valid` reste cohérent : aucun défaut structurel n'est trouvé, mais la politique d'écriture des fichiers compilateur n'est pas établie. Le statut global demeure `partial`, jamais une autorisation de build. Le blocage est correct et doit rester actif.

## Fichiers, clés et empreintes attendus

Pour la racine du Run D, le code lit les chemins suivants, **indépendamment de l'inventaire SDK/libs** :

| Chemin dans l'image | Vérification / source exacte |
|---|---|
| `/opt/velxio-mcp-source/backend/app/services/espidf_compiler.py` | Lecture/parse à `checks.py:107–109`, empreintes de deux fonctions à `110–117`, constantes et helper à `118–140`. |
| `/opt/velxio-mcp-source/backend/app/services/esp-idf-template/main/` | Listing et hash des fichiers présents à `checks.py:142–146`. Dans le snapshot revu : `CMakeLists.txt`, `main.c`, `main.cpp`, `velxio_compat.h`. |
| `/opt/velxio-mcp-source/backend/app/services/arduino_cli.py` | Lecture/parse et empreinte de `compile` à `checks.py:147–152`. |

Le packaging prévoit bien ces chemins : `packaging/mcp-compact/prepare.py:69–73` crée `payload/source/backend/app/services/`, copie les deux sources et tout `esp-idf-template/` ; `packaging/mcp-compact/Dockerfile:10` copie ce contenu dans `/opt/velxio-mcp-source/`. Il n'y a pas d'erreur de préfixe `backend/app` dans ce plan. Cela établit le contenu **prévu**, pas une inspection des fichiers réellement présents dans l'image D.

Dans `espidf_compiler.py:96–107`, les clés attendues et présentes dans le worktree sont :

- `_MAIN_RESERVED_NAMES` : `main.cpp`, `main.c`, `sketch.ino.cpp`, `sketch_translated.c`, `velxio_compat.h`, `CMakeLists.txt`, `idf_component.yml` (comparaison casefold).
- `_USER_FILE_PREFIX = 'user_'` ; `_COMPILED_SUFFIXES = ('.c', '.cpp')`.
- `_user_main_name`, à `espidf_compiler.py:110`, doit garder exactement le corps de mapping comparé à `checks.py:125–137` ; les sélections `entry_file = files[0]`, `ino_files[0]`, `f['name'] == 'sketch.ino'` sont aussi requises à `checks.py:138–140`.

Les trois empreintes AST attendues sont inchangées. Voici les calculs **sur les mêmes fichiers locaux, sous Python 3.13.5** :

| Fonction | Empreinte attendue = `ast.dump` par défaut | Contrôle local avec `show_empty=True` |
|---|---|---|
| `_write_arduino_user_files` (`espidf_compiler.py:140`) | `3af9f3fc8c905d28a83933bfb4bba6ebe95053bef8a22c986cc66bbfc4d913b3` | `93fbfa4234defbbde66b9f9812d9a7d5319a2ece6c73578c97d3177f283a928b` |
| `_compile_in_dir` (`espidf_compiler.py:5771`), après projection legacy | `39faa596be9d697da91d5bb066db672ea64dcc430f767d070f9b8189569ec3fd` | `df919c0a9bb7d76ae6f5741f272a1a749ae48f69ea3aabe7e97330593727b0f8` |
| `compile` (`arduino_cli.py:585`) | `58c4fd9f87d4aedfe6ef19e2a907075ae52bb5cea73ae3db6ff986025ff562e9` | `635daa27bf729483ff7ec797a0c7d6cd4a88da1fbd0eaf457b2a5352909082ce` |

La colonne de droite est une **sonde locale du changement de format**, pas un hash mesuré dans l'image ni une nouvelle liste d'acceptation Python 3.12. Le calcul exact sous 3.12 doit être capturé par la commande proposée.

Preuve minimale de la dépendance de représentation, obtenue localement :

```text
Python 3.13.5, dump par défaut :
FunctionDef(name='f', args=arguments(), body=[Pass()])

Python 3.13.5, show_empty=True :
FunctionDef(name='f', args=arguments(posonlyargs=[], args=[], kwonlyargs=[], kw_defaults=[], defaults=[]), body=[Pass()], decorator_list=[], type_params=[])
```

Python 3.12 conserve ces listes vides dans son dump et n'a pas le paramètre `show_empty` ajouté en 3.13. Le code utilise un appel sans convention canonique explicite (`checks.py:116`, `150`). Le `ast.dump` installé sur le poste est lisible dans `/usr/lib/python3.13/ast.py:113` et expose `show_empty=False` ; le Run D est identifié en 3.12 par ses frames `/usr/local/lib/python3.12/...` et son membre toolchain `usr/local/bin/python3.12`.

Contrôle local en lecture seule : `CompilerPolicy('.')` réussit avec `prefix='user_'`. À fichiers inchangés, une sonde en mémoire faisant seulement conserver les champs vides au dump échoue dès le **premier appel** avec `ValueError: Compiler file-writing behavior changed; review required`. La projection `legacy_file_behavior` (`checks.py:64–99`) demeure inchangée et ne normalise pas le format du dump. Des tests policy réussis sur le poste 3.13 ne couvrent donc pas cette admission sous le Python 3.12 de l'application.

Hashes SHA256 des octets des sources locales qui ont servi à cette comparaison :

- `backend/app/services/espidf_compiler.py` : `3e25c07dab7eebbd86980b8da3dc59917da323803ef2a046aafea1a5e43ad154`.
- `backend/app/services/arduino_cli.py` : `cb7480afa1f3eb0314ef69cd9a22ec586f40060508bc84071478c20c17186238`.

Ce sont des hashes de fichiers complets, distincts des empreintes AST de fonctions et des préimages de la base ancienne.

## Ce qui manque — et ce qui n'est pas en cause

- **Politique dans l'application :** il manque une convention de sérialisation AST stable entre les runtimes revus 3.12/3.13. L'existence de tous les fichiers ne suffit pas à rendre ces empreintes portables.
- **Snapshot de l'image :** les preuves D exportées ne fournissent pas son listing/SHA ni l'exception originale de `CompilerPolicy`. Cette mesure manque pour exclure un problème supplémentaire de copie/droits/octets ; ne pas inventer un fichier absent. La commande ci-dessous imprime ces éléments sans importer de service compilateur.
- **Inventaire :** `proof-d/inventory/inventory.json` contient les trois clés exactes `GxEPD2`, `Adafruit GFX Library`, `Adafruit BusIO`, avec `path`, `sha256`, `source_root`, `tree_sha256`. Le check D produit trois `dependency_manifest_verified`, sans `inventory_unverified` ni `dependency_absent`. Les clés toolchain `esp32:esp32:esp32|arduino` et `esp32:esp32:esp32|espidf` sont présentes, `test_only:false`, version `5.5.4`, racines `/opt/esp-idf-v5` et `/opt/arduino-esp32-3`. Les SHA des deux manifests transférés correspondent à ceux de `inventory.json`. Leur inventaire n'est pas un inventaire du snapshot de policy ; ajouter une entrée de bibliothèque ne corrigerait pas ce refus.
- **Projet `.vlx` :** Run D valide la structure de `p_5f7b0fde507b48cc9477b2af8ed93526`, version exacte `b8248089e546dd01b8418feae1fbc515626eee67da61c93ada123d9d71365aa8`. Le fichier revu porte `boardKind=esp32`, `languageMode=arduino`, les trois bibliothèques et un unique `sketch.ino`. Aucune clé de projet ne paramètre `CompilerPolicy` ; il n'y a pas de champ policy à ajouter au `.vlx`.
- **Template live vs snapshot :** l'owner D indique `blockers=[]`, mais cela concerne le template live du service (`espidf_compiler.py:5714`, `espidf_offline.py:60–64`), pas les lectures sous `/opt/velxio-mcp-source`. Ce n'est pas une preuve du snapshot de policy.
- **Arduino startup :** les erreurs d'index/core dans `smoke-d.stderr` restent réelles et indépendantes. Elles ne sont pas lues par `CompilerPolicy`, qui ne charge aucun service et n'installe rien ; elles ne justifient ni un contournement de ce garde-fou ni l'annonce d'un build effectué.

Preuves locales lues : `/home/dev/review-proofs/d/smoke-d.stdout`, `smoke-d.stderr`, `env-d.list`, et les trois JSON sous `proof-d/inventory/`. SHA256 de `smoke-d.stdout` : `9dfcac5f7bb0065f6b5453114f1df215d176135935108d20b624c2f40537d27c` ; de `inventory.json` : `21acd4c66ae76ad3d1a267a21ee8ea4d20fc1c7513c27327f650eff388c2b100`.

## Correctif minimal proposé, non appliqué

Après confirmation des octets et de la première exception dans l'image, stabiliser **uniquement le calcul des empreintes** de `CompilerPolicy` : un sérialiseur AST canonique versionné, revu pour 3.12/3.13, reproduisant la convention des empreintes originales (omission des listes vides/champs optionnels sans valeur, conservation des nœuds et champs sémantiques). Conserver la projection legacy avant ce calcul et les **trois empreintes originales** ci-dessus, les contrôles de constantes/helper/sélection de sketch, puis toutes les vérifications template/SDK existantes. Un simple ajout `show_empty=False` ne fonctionne pas sur 3.12.

Valider ce futur correctif sur les deux runtimes, avec les mêmes sources et mutations sémantiques refusées ; une source manquante, une modification de mapping/écriture ou un schéma AST non revu doit toujours bloquer. Le garde-fou `builds.py:201–202` reste inchangé. Aucune nouvelle empreinte tirée aveuglément de l'image, changement de Python/toolchain, modification du `.vlx` ou installation n'est proposé pour faire disparaître le refus.

## Commande de vérification manager, lecture seule

À exécuter **ultérieurement dans une nouvelle instance isolée** de l'image exacte du Run D, sans mounts/ports de production, sans startup applicatif et sans compilateur. Cette commande n'a pas été exécutée ici. Elle donne la première exception non masquée, les fichiers réellement présents, les hashes live/snapshot et les empreintes par défaut du Python réel :

```sh
REVIEW_IMAGE='<ID immuable de l image exacte du Run D>'
docker run --rm -i --pull=never --network=none --read-only \
  --env PYTHONPATH=/app --env PYTHONDONTWRITEBYTECODE=1 \
  --entrypoint /usr/local/bin/python3 "$REVIEW_IMAGE" - <<'PY'
import ast, hashlib, inspect, json, sys, traceback
from pathlib import Path
from app.mcp.compact.checks import CompilerPolicy, legacy_file_behavior
root = Path('/opt/velxio-mcp-source')
print(json.dumps({'python':sys.version, 'ast_dump_signature':str(inspect.signature(ast.dump)),
                  'source_root':str(root)}))
files = ['espidf_compiler.py', 'arduino_cli.py', 'esp-idf-template/main/CMakeLists.txt',
         'esp-idf-template/main/main.c', 'esp-idf-template/main/main.cpp',
         'esp-idf-template/main/velxio_compat.h']
for name in files:
    paths = [root / 'backend/app/services' / name, Path('/app/app/services') / name]
    for path in paths:
        try:
            raw = path.read_bytes()
            print(json.dumps({'path':str(path), 'size':len(raw),
                              'sha256':hashlib.sha256(raw).hexdigest()}))
        except OSError as error:
            print(json.dumps({'path':str(path), 'error':repr(error)}))
functions = [('espidf_compiler.py', '_write_arduino_user_files', '3af9f3fc8c905d28a83933bfb4bba6ebe95053bef8a22c986cc66bbfc4d913b3'),
             ('espidf_compiler.py', '_compile_in_dir', '39faa596be9d697da91d5bb066db672ea64dcc430f767d070f9b8189569ec3fd'),
             ('arduino_cli.py', 'compile', '58c4fd9f87d4aedfe6ef19e2a907075ae52bb5cea73ae3db6ff986025ff562e9')]
for filename, name, expected in functions:
    try:
        tree = ast.parse((root / 'backend/app/services' / filename).read_bytes())
        node = next(n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)
        if name == '_compile_in_dir':
            node = legacy_file_behavior(node)
        actual = hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest()
        print(json.dumps({'function':name, 'expected':expected, 'actual_default_dump':actual,
                          'matches':actual == expected}))
    except Exception as error:
        print(json.dumps({'function':name, 'error':repr(error)}))
try:
    policy = CompilerPolicy(root)
except Exception:
    traceback.print_exc()  # Exception originale, pas le résumé de ProjectChecker.
    sys.exit(1)
print(json.dumps({'compiler_policy':'verified', 'prefix':policy.prefix,
                  'reserved':sorted(policy.reserved), 'sources':policy.sources}))
PY
```

Avant correctif, le résultat attendu pour des fichiers identiques sous 3.12 est un mismatch du premier hash, puis `ValueError` à `checks.py:117`. Si c'est d'abord `FileNotFoundError`, `PermissionError`, ou si les hashes des fichiers diffèrent, documenter et corriger ce défaut de snapshot avant de conclure sur le format AST. Après le correctif proposé, cette même commande doit terminer avec `compiler_policy=verified` tout en conservant les empreintes de référence ; cela ne prouvera toujours ni un build réel ni l'absence de tentative d'installation au startup.
