# Contrats et catalogue compact — jalon 2

Module indépendant : aucune inscription FastMCP, aucun import de `server.py`, de l'UI ou des compilateurs. `Catalog.search_catalog`/`get_reference` sont opérationnels depuis le jalon 2 ; `ProjectStore.save_project`/`read_artifact` le sont au sous-jalon 3a et `ProjectChecker.check_project` au 3b. `BuildService.build_project` ajoute au 3c l'orchestration persistante injectable ; **son intégration réelle au propriétaire REST est bloquée**, sans compilateur réel par défaut. `TOOL_SCHEMAS` documente les **six** noms et leurs entrées/sorties JSON Schema. Aucun `test_project`.

## Utilisation locale sans installation

Depuis la racine du dépôt :

```sh
node scripts/generate-mcp-compact-catalog.cjs > /tmp/velxio-compact-catalog.json
PYTHONPATH=backend python3 - <<'PY'
from app.mcp.compact import Catalog
catalog = Catalog.from_repository('.')
print(catalog.search_catalog(query='epaper'))
print(catalog.get_reference(id='component:epaper-1in54-bw'))
print(catalog.get_reference(id='example:epaper-1in54-uno-hello', section='code'))
PY
python3 -m unittest discover -s test/backend/unit -p test_mcp_compact_catalog.py -v
```

Le runtime Python n'utilise que la bibliothèque standard. La génération requiert Node et les paquets Babel **déjà présents** (`@babel/parser`, `@babel/traverse`, `@babel/core`, `@babel/plugin-transform-typescript`). Les tests de schémas utilisent Ajv déjà présent. Ni `npm`, ni téléchargement, ni installation automatique. Une dépendance absente produit un échec explicite. La génération écrit sur stdout ; `from_repository` capture l'instantané en mémoire, sans écrire de stockage projet ou de fichier généré dans le dépôt. L'instantané dérivé (~2,3 Mo) n'est pas commité : les sources versionnées et le générateur sont son autorité.

## Extraction reproductible et limites

Le générateur parse les AST TypeScript, suit les dépendances des déclarations nécessaires et transforme seulement ces expressions/aides de génération en JavaScript dans une VM à durée bornée (2 s par évaluation, 30 s pour le sous-processus Python). Il **n'importe jamais un module navigateur** et n'exécute pas les autres instructions du module : pas de `registry.load()`, `fetch`, DOM, installation de bibliothèques ou service. Un identifiant non résolu, import non local, cycle, injection de registre non reconnue, ID dupliqué ou entrée structurée non UTF-8 provoque un échec ; aucune liste de secours tronquée.

Il s'agit d'un extracteur de **sources locales de confiance**, pas d'un bac à sable pour du JavaScript hostile. Les changements de conventions AST doivent être revus ; une future forme d'ajout runtime différente des appels `data.components.push({...})` nécessite une adaptation explicite. Les ajouts d'overlay privé/dynamiques ne sont pas inventés : l'import `@pro/data/proExamples` est résolu vers le stub OSS réel. Aucun chargement de l'ancien dépôt.

Sources de données : JSON complet `components-metadata.json`, injections du registre, labels/FQBN/capacités de `types/board.ts`, vocabulaire de recherche, pins/aliases des Web Components ESP32 et format Wokwi natif, configurations/pins e-paper, agrégat **complet** `exampleProjects` et toutes ses dépendances TS/`?raw`. Au jalon 2 : **166 composants, 30 cartes, 328 exemples**. Les tests fixent ces comptes pour détecter un changement à revoir, pas pour tronquer l'extraction.

`revision` est le SHA-256 du payload JSON déterministe émis par le générateur, avec la version des outils Babel et le manifeste `{path,sha256}` de tous les fichiers consommés, y compris le générateur. Pas d'horodatage ni chemin absolu. Les sources de chaque entrée ont chemin, ligne et hash des **octets originaux**. Les structures calculées peuvent citer leur déclaration agrégée ; le manifeste global conserve les dépendances exactes. `Catalog(snapshot)` attend un instantané généré de confiance ; ce constructeur ne prétend pas authentifier un document fourni par un tiers.

Un fichier `?raw` existant (`galaksija-rom.c`) n'est pas strictement UTF-8. Son texte décodé suit la convention UTF-8 du frontend, mais les octets originaux sont conservés dans `raw_inputs` avec base64 et hashes, sans perte silencieuse ; ils ne sont exposés que par la section explicite `code` du projet concerné. Les entrées structurées invalides échouent au lieu de remplacer des octets.

Les broches ESP32 viennent des tableaux réellement associés à chaque `BOARD_CONFIGS`, y compris les alias physiques 16/RX2 et 17/TX2. Les broches e-paper et `panelKind` viennent des définitions existantes ; SPI est sourcé au raccordement `attachSpiDevice`. Pour les composants/cartes dont aucune liste n'a été extraite, `pins:"unknown"` avec une limite explicite ; aucun nom de pin n'est déduit d'un simple compte. Protocole et initialisation restent `unknown` lorsqu'aucune extraction établie ne les documente. Aucune séquence d'initialisation n'est synthétisée.

Les bibliothèques sont **déclarées par les exemples**, avec leur provenance (y compris la constante `EPAPER_LIBS`) ; elles ne sont ni installées, ni inférées des `#include`, ni garanties exhaustives. Le résumé regroupe les noms avec un exemple de source et un nombre de preuves ; la section `libraries` donne les déclarations et leurs sources. Une carte présente au catalogue n'est pas une preuve de support de compilation/simulation installé.

## Contrats et réponses bornées

- `search_catalog(query="",kind="all",limit=5,offset=0)` : recherche de tous les mots normalisés dans noms, IDs, tags, aliases, descriptions et mots-clés réels ; ordre stable par ID. Ce classement simple ne prétend pas reproduire les poids/synonymes multilingues de l'UI. De 1 à 50 résultats ; aucun code/SVG dans les résultats. Pagination sans état : `offset` entier de 0 à 1 000 000, `total` indique le nombre de résultats de la recherche, `has_more` indique s'il reste des résultats après cette page. Pour avancer, ajouter le nombre d'éléments reçus à l'offset ; au-delà de `total`, la page est vide et `has_more:false`. La réponse conserve `revision` ; le client peut recommencer à zéro si elle change entre deux pages. Aucun curseur n'est exposé ni produit. Un ancien argument `cursor` est ignoré, quelle que soit sa valeur, avant validation des arguments MCP. La taille de page peut changer.
- `get_reference(id,section="overview")` : ID canonique `component:…`, `board:…` ou `example:…`. Les clés/aliases non ambigus sont acceptés ; une collision exige un ID qualifié. Sections : `overview,pins,attrs,protocol,libraries,init,limitations,sources,files,project,code`. Par défaut : résumé, broches/attributs/protocole, libs sourcées, init/limites/sources ; pour un exemple, noms, tailles/hashes des fichiers et dépendances. Ni corps de source, ni VFS, ni sourceC ou blobs embarqués par défaut. `files` est un manifeste ; `project` est débarrassé des contenus source ; **seul `code` restitue les sources d'origine**, y compris celles des groupes et chips.
- Chaque réponse sérialisée par le module est ≤**24 KiB UTF-8**. Un dépassement de section catalogue devient `quota_exceeded`, sans tronquer du code ni annoncer un faux artefact consultable. Au sous-jalon 3a, `read_artifact` lit uniquement les snapshots projet persistés, sans créer d'artefact catalogue. Query ≤256 caractères, ID ≤240 ; arguments inconnus et types invalides refusés, à l’exception de l’ancien `cursor` ignoré sur les six outils MCP. Les réponses restent des objets JSON ; le futur adaptateur MCP devra sérialiser sans ajouter une enveloppe illimitée.

Contrats projet et état au sous-jalon 3a :

| Nom | Entrée / résultat prévu |
| --- | --- |
| `save_project` | Création par `document` natif ; mise à jour par `project_id,expected_version` CAS et **soit** snapshot complet **soit** `changes`. Résultat : ID/version/hash, artefact `.vlx` et `download_url:null` tant qu'aucun vrai endpoint de téléchargement n'existe. L'URL future sera celle de l'artefact, sans promesse d'un projet ouvrable dans l'UI. |
| `check_project` | `project_id,version` exacts ; résultat `valid|invalid|partial`, contrôles effectués/indisponibles, résumé et artefact de diagnostic. |
| `build_project` | Exactement deux opérations : `start(project_id,version,board_id)` et `status(build_id)`. Réponses compactes avec état et métadonnées d'artefacts. Aucun autre mode. |
| `read_artifact` | ID opaque, offsets en octets, 1..12288 octets par lecture, encodage UTF-8/base64 ; taille/hash/fin/troncature explicites. |

Les modifications ciblées `changes` sont `set`/`remove` sur des JSON Pointers RFC 6901 sous `name,boards,fileGroups,folderGroups,components,wires,activeBoardId`. Pour `set`, `value` est obligatoire ; pour `remove`, il est interdit. L'applicateur 3a décode les échappements, refuse les chemins inexistants pour remove, permet l'ajout d'une clé d'objet par set, remplace uniquement un index existant d'un tableau (pas d'insertion implicite), puis valide le **document résultant** et publie un snapshot après CAS. Pas de changement de format/version par patch.

Le schéma du document préserve les objets internes de l'UI, dont options/SPIFFS/SD. Le stockage 3a applique les validations structurelles et quotas décrits ci-dessous ; il ne fait aucune interprétation électrique. Le contrôle 3b reste structurel. Le build 3c est décrit ci-dessous : aucun vrai firmware n'a été compilé et aucun faux succès réel n'est annoncé.

## Sous-jalon 3a — snapshots natifs et lecture bornée

```python
from tempfile import TemporaryDirectory
from app.mcp.compact import ProjectStore

with TemporaryDirectory() as root:
    store = ProjectStore(root)  # Racine prévue par défaut : /app/data/mcp-compact
    saved = store.save_project(document=native_vlx_document)
    page = store.read_artifact(artifact_id=saved['project_artifact_id'], length=4096)
```

Aucun accès au vrai `/app/data` n'a été effectué pendant le développement/tests. Aucun transport n'est modifié. Le constructeur seul crée la racine injectée, en parcourant chaque parent par descripteur et `O_DIRECTORY|O_NOFOLLOW` ; importer le module ne crée rien. Les appels retournent l'enveloppe `{ok,...}` des contrats.

`save_project` crée un projet ou exige **les deux** `project_id` et `expected_version` pour modifier un projet existant, par snapshot ou patch. CAS vérifié sous verrou avant tout patch/publication. Le document résultant est validé : format/version natifs, types et limites des conteneurs, IDs uniques, liens carte/groupe et endpoints d'objets existants, coordonnées finies ; les propriétés internes/attributs inconnus de l'UI sont conservés. Les propriétés e-paper, formes des fils, rotations, bibliothèques, options, SPIFFS et SD sont sauvegardées sans passer par l'export UI qui omet certains champs. SPIFFS utilise le champ natif **`contentB64`**, avec `size` conservé ([boardOptions.ts:47](../../../../frontend/src/types/boardOptions.ts#L47)).

La version est le SHA-256 des octets JSON UTF-8 canoniques : clés d'objets triées, séparateurs compacts, ordre des tableaux conservé, valeurs finies, clés texte et valeurs JSON natives uniquement. **Tous les champs fournis, y compris `exportedAt`, participent au hash** : ceci précise/remplace l'ancienne proposition d'exclure cet horodatage dans l'inspection, afin de ne perdre aucune métadonnée. Même contenu + CAS courant → même version et même artefact. Un autre projet reçoit un ID et un ID d'artefact distincts, même avec des octets identiques. `download_url` reste `null`.

Stockage POSIX (stdlib, `flock`) :

```text
<root>/.lock
<root>/projects/p_<uuid>/head.json
<root>/projects/p_<uuid>/versions/<sha256>.vlx
<root>/projects/p_<uuid>/versions/<sha256>.json
<root>/artifacts/a_<uuid>.json
```

Les IDs sont générés par le serveur et strictement vérifiés avant utilisation. Les noms utilisateur ne deviennent jamais des chemins de stockage. Les manifestes croisés lient artefact, projet, version, taille et hash ; une substitution d'index vers un autre projet est refusée. Un ID d'artefact est une capacité locale de lecture ; aucun système de comptes/autorisation multiutilisateur n'est ajouté ici.

Un verrou global interprocessus exclusif sérialise les sauvegardes ; les lectures ont un verrou partagé. L'ouverture de chaque répertoire, fichier, parent, racine et verrou utilise `dir_fd`/`O_NOFOLLOW`. Racine remplacée, lien symbolique, hardlink, fichier spécial ou manifeste incohérent : refus explicite. La racine et ses fichiers sont créés avec modes 0700/0600. Les accès restent relatifs aux descripteurs ouverts ; aucune résolution par chaîne fournie par le client. Ceci protège les chemins ; ce n'est pas une protection contre un administrateur capable de modifier les octets physiques du volume.

Publication : fichier temporaire unique dans le répertoire destination, écriture/flush/`fsync`, `rename` atomique, `fsync` du répertoire. Les versions et index sont immuables ; seule la tête peut être remplacée. La tête est publiée **en dernier**, après snapshot, manifeste et index. Une interruption antérieure laisse l'ancienne tête et ses artefacts lisibles ; les fichiers déjà écrits sont conservés et une nouvelle tentative avec le même contenu/CAS reprend un snapshot incomplet. Il ne s'agit pas d'une transaction atomique multi-fichiers : si le système échoue **après** le rename de la tête, le résultat peut être indéterminé pour l'appelant, mais la tête est toujours un JSON complet vers une version complète. L'erreur l'indique ; un CAS devenu périmé n'est jamais écrasé. Un arrêt brutal peut laisser des `.tmp-*`/versions orphelines comptés dans le quota ; pas de purge/réparation destructive automatique.

Quotas appliqués avant publication : **2 MiB** pour le `.vlx` canonique et pour le total décodé sources/SD/SPIFFS, **128 fichiers** au total, **256 KiB UTF-8 par source**, y compris `sourceC` embarqué ; tableaux 8 cartes/512 composants/1024 fils. Les noms rejettent absolus POSIX, lecteurs Windows/UNC, NUL/contrôles, backslash, segments vides/`.`/`..`, noms Windows ambigus ; collisions NFC/casefold, fichier/répertoire et basenames aplatis des groupes ESP32/ESP-IDF refusés. Aucun renommage ou écrasement silencieux.

Le quota global est **256 MiB** de fichiers persistés par défaut, injectable pour tests. L'usage est compté sous le même verrou, via descripteurs, sans suivre les liens. Un dépassement retourne `quota_exceeded`, conserve tous les fichiers existants et n'augmente pas le quota, ne bascule pas de racine/moteur et ne purge rien. La marge conservatrice inclut les manifestes/tête ; le pic transitoire de copies/fsync et les allocations physiques du système de fichiers ne sont pas un quota disque de l'OS.

`read_artifact` n'accepte que l'ID opaque, jamais un chemin/projet/version fourni séparément. Hash, taille et manifestes sont vérifiés, puis la réponse fournit offset/next_offset en **octets**, taille totale, hash SHA-256 et eof/truncated. `length` vaut 1..12288, **une borne supérieure** : UTF-8 réduit la fin pour ne couper aucun caractère ; offset au milieu d'un caractère ou longueur incapable de le contenir → erreur explicite. Base64 lit n'importe quelle tranche d'octets. L'échappement JSON peut réduire davantage une tranche UTF-8 pour garder la réponse complète ≤24 KiB ; `next_offset` permet de continuer sans perte. EOF à la taille exacte retourne une tranche vide ; offset supérieur refusé. Les snapshots sont au plus 2 MiB et sont intégralement vérifiés en mémoire avant lecture bornée. Aucun TTL, effacement ou artefact de compilation n'est ajouté.

## Vérification et arrêt

Tests ciblés par `unittest` et validation des six schémas avec Ajv local : défaut 5, pagination exhaustive, curseurs/requête/kind/révision, reproductibilité/provenance, extraction échouant explicitement sur dépendance navigateur, aliases, pins ESP32/e-paper, dépendances réelles, absence de code par défaut sur **chaque** entrée, quotas multioctets et CAS/patch/start/status des schémas. Les tests ne compilent et ne simulent rien. Aucun fichier existant d'UI/transport/stockage/build/configuration n'est modifié.

Tests 3a stdlib : redémarrage, champs UI natifs, ancien snapshot/idempotence, CAS à deux vrais processus (un gagnant), RFC6901/allowlist/validation résultante, échecs avant publication de tête/manifeste et reprise, fsync/temp, quotas, encodages/noms/collisions, racine/parents/fichiers/verrou/index symboliques et hardlinks, traversée/isolation et hashes. Ajouter aux 20 régressions catalogue : `python3 -m unittest discover -s test/backend/unit -p 'test_mcp_compact*.py' -v`.

## Sous-jalon 3b — contrôle exact et artefact de rapport

```python
from app.mcp.compact import Catalog, ProjectChecker, ProjectStore
store = ProjectStore(temporary_root)
checker = ProjectChecker(store, Catalog.from_repository(repository_root))
result = checker.check_project(project_id=saved_id, version=exact_sha256)
page = store.read_artifact(artifact_id=result['diagnostic_artifact_id'])
```

`check_project` accepte exactement `project_id` et un hash `version`, jamais `latest`, une tête implicite ou un chemin. Il charge `.vlx`/manifeste/index par les primitives sécurisées du store, vérifie le hash et la validation native ; **`head.json` n'est jamais lu**. Une v1 reste contrôlable après v2. Juste avant la publication du rapport, la même version est revérifiée sous `flock` exclusif. Aucun snapshot/tête n'est modifié.

Contrôles : IDs et références du document natif ; IDs de cartes/composants dans la révision exacte du catalogue injecté ; types/options/min/max des attributs connus et `panelKind` ; board/langage documenté ; noms déclarés des dépendances ; endpoints et listes de pins documentées ESP32/e-paper. Une propriété, une liste de broches, un nom de bibliothèque ou un support non documenté produit **`unknown`**, jamais une documentation ni une disponibilité inventées. Les aliases physiques ESP32 16/RX2 et 17/TX2 sont reconnus par coordonnées des pins sources.

Les connexions physiques non orientées répétées sont signalées. Le contrôle détecte un même net GPIO raccordé à plusieurs rôles distincts SCK/SDI/CS/DC/RST **du même panneau** e-paper : chevauchement structurel, sans mesure de tension ou assertion sur l'exécution du firmware. Des GPIOs multiples sur un net produisent une direction `unknown`, pas une panne électrique supposée. Le partage normal d'un même signal SPI entre plusieurs panneaux n'est pas une erreur.

Les noms du template ne sont pas une liste métier inventée : `CompilerPolicy` parse l'AST local de `espidf_compiler.py`, extrait `_MAIN_RESERVED_NAMES`, `_USER_FILE_PREFIX`, `_COMPILED_SUFFIXES`, vérifie la forme AST du helper et les empreintes AST des fonctions d'écriture/sélection concernées ; il lit aussi les noms/hashes des vrais fichiers du template et vérifie l'AST du chemin arduino-cli. **Aucun import ni exécution de ces services.** Les empreintes AST décrivent le comportement de la base inspectée ; toute dérive non reconnue (ou différence de représentation AST de Python) devient `template_policy_unknown`/contrôle indisponible, à revoir explicitement.

Le rapport signale les collisions après aplatissement et renommage `user_…`, les fichiers de configuration/support appartenant au template en ESP-IDF pur, le sketch principal réellement choisi (chemin/index dans le rapport) et plusieurs `.ino` sans `sketch.ino` explicite. Le fichier C/C++ utilisé comme entrée de secours ESP32 n'est pas compté deux fois parmi les helpers ; hors ESP32, l'absence de `.ino` est signalée comme risque de sketch vide, sans inventer un sketch utilisateur compilé. Aucune compilation, installation ou analyse sémantique C/C++ n'est effectuée.

Sans inventaire injecté, toute disponibilité de dépendance reste inconnue. `LibraryInventory(root, entries, complete=False)` prend une table locale `{nom:{path:relatif,sha256:attendu}}` et vérifie **à chaque check** des fichiers preuves, via parents/`O_NOFOLLOW`, fichier régulier sans hardlink, ≤1 MiB par preuve, ≤128 entrées. Le rapport conserve leur hash et le hash de l'inventaire. Une preuve altérée ou symbolique invalide la vérification et rend la disponibilité inconnue. Une entrée présente signifie seulement « manifeste prouvé », pas compatibilité ou build réussi ; une entrée manquante est `dependency_absent` uniquement si l'appelant a déclaré l'inventaire **complet** et que ses preuves ont été vérifiées. La complétude reste une hypothèse de confiance de l'injection, pas un scan automatique de toutes les installations du système.

Le résultat distingue `structure_status:valid|invalid` et `status:invalid|partial`. Même structurellement valide, il reste **partial** : `electrical_validation`, `functional_simulation`, `compiler_execution` sont toujours indisponibles. `checks_performed`/`checks_unavailable` détaillent cette portée. Les diagnostics sont `{code,path,severity,message}` avec JSON Pointer RFC6901, sévérités `error|warning|unknown|info` ; présence d'erreurs structurelles → invalid. Les messages restent concis et n'incluent aucun corps source.

Le résumé retourne au plus 20 diagnostics (moins si l'échappement JSON l'exige), les comptes et `issues_truncated`. Les chemins du résumé sont bornés à 512 caractères et marqués `path_truncated` si nécessaire ; **les chemins complets et tous les diagnostics restent dans l'artefact**, sans suppression silencieuse. Réponse ≤24 KiB ; limite complète 4096 diagnostics/2 MiB, dépassée → `quota_exceeded` sans faux rapport complet. Un défaut d'intégrité du snapshot échoue avant le contrôle, sans faux diagnostic de circuit.

Extension locale minimale du store : `projects/<id>/reports/<report_sha>.json` et `<report_sha>.meta.json`, index opaque existant avec `kind:check_report`, lié au projet et à la version contrôlée. Hash propre au rapport (distinct du hash projet), métadonnées/croisement/quota et publication atomique par les mêmes primitives ; répétition avec mêmes sources/catalogue/inventaire → même artefact immuable. `read_artifact` accepte désormais ces rapports JSON **et** les anciens `.vlx`, avec les mêmes tranches UTF-8/base64, hashes et limites. Aucun rapport de build, route de téléchargement, TTL, purge ou transport n'est ajouté.

Tests 3b : ESP32/e-paper valide structurellement/partial, pins invalides/inconnues, IDs/attrs/panelKind, rôles GPIO/doublons, langue/support, noms et disponibilité des bibliothèques, preuve d'inventaire modifiée/symbolique, v1 exacte après v2 avec tête illisible, rapport complet relisible/hash/bornage/quotas/liens, collisions template/principal/multi-ino et politique changée → unknown. Test explicite accepté : changer `exportedAt` change la version. Régressions catalogue et store 3a conservées.

## Jalon 3c — orchestration de build, intégration réelle bloquée

`BuildService(store, checker, adapter=None, toolchains=None)` expose **uniquement** `await build_project(action="start",project_id=…,version=…,board_id=…)` et `await build_project(action="status",build_id=…)`. Aucun mode compile/run/install/cancel supplémentaire. Sans adaptateur, `start` retourne `owner_integration_required`, sans job ni installation. Les seuls callbacks exécutés par les tests sont des **doubles explicitement contrôlés**, jamais un vrai compilateur. Tous leurs résultats persistés et réponses ont `test_only:true`, un résumé « TEST DOUBLE », et des manifests de toolchain `test_only:true`. Un adaptateur ou une preuve de toolchain de production ne devient pas opérationnel par défaut.

### Interface interne propriétaire requise, sans changement de route

La route existante [compile.py:1030](../../../../backend/app/api/routes/compile.py#L1030) possède aujourd'hui le job, l'admission par `build_queue.lane_for` et l'appel `_run_compile` ; [BuildQueue.slot](../../../../backend/app/services/build_queue.py#L325) est lié à **un processus et une boucle**. Le chemin [_run_compile](../../../../backend/app/api/routes/compile.py#L882), notamment [ligne 963](../../../../backend/app/api/routes/compile.py#L963), peut appeler `ensure_core_for_board` et donc installer un core. Aucun import de cette route, appel HTTP, appel `_arduino.compile`, lancement de worker/processus/compiler ou nouvelle file indépendante n'est introduit ici.

`OwnerQueueAdapter(lane_for, compile_offline, test_only=True, name=…)` précise l'interface de raccordement : recevoir **la même fonction et les mêmes gates** que REST, dans son processus/boucle ; attendre `slot(priority=20,key=…)`, notifier `running` seulement après admission, puis appeler une coroutine offline injectée avec les entrées et un callback texte des logs. PID et boucle sont vérifiés. Les tests d'admission utilisent tantôt un gate factice explicite, tantôt **le vrai gate partagé** de `app.services.build_queue` occupé par des admissions simulées, avec compilation toujours factice. Aucune preuve d'intégration REST opérationnelle n'en est déduite.

**Blocage précis pour une intégration réelle ultérieure :** le propriétaire REST doit fournir un hook interne qui conserve admission/priorité/scope/déduplication, appelle une voie de compilation garantie **sans** `ensure-core`, téléchargement ou installation, livre des octets de firmware décodés et des logs, et protège/drain l'exécution contre une déconnexion/annulation. L'orchestrateur ne doit pas être enveloppé dans une deuxième admission de la même file. Ce hook n'existe pas actuellement comme interface offline publique vérifiée ; modifier la route pour le créer reste hors périmètre et nécessite une nouvelle consigne. Aucun contournement ni « fallback Arduino » n'est proposé.

### Préflight et provenance

Chaque `start` charge la version exacte par les primitives sécurisées, exécute `check_project`, vérifie le hash du rapport complet et cherche **l'instance** `board_id`. Il refuse une structure invalide, `compiler_policy_unknown`, une carte/langue sans FQBN documenté, MicroPython/non-compilable, un manifeste absent/non documenté ou une disponibilité de dépendance inconnue. Une dépendance absente d'un inventaire complet vérifié donne `dependency_unavailable` ; aucun install n'est tenté. Les limites électriques/fonctionnelles ne sont pas transformées en faux tests de fonctionnement.

Le payload injecté conserve groupe et ordre des fichiers, options, bibliothèques, langage, SPIFFS et le sous-ensemble natif complet de la carte (SD et champs futurs inclus). SPIFFS passe aussi dans la forme compiler `content_b64`, avec `contentB64` d'origine préservé dans le sous-ensemble natif. La version entière reste la référence ; une v2 ultérieure ne modifie pas un build v1. Le payload interne dérivé, éventuellement redondant entre native/compiler, est borné à **8 MiB**, sans modifier le quota du projet natif.

`ToolchainInventory` étend les preuves locales vérifiées du 3b : un manifeste JSON haché `{kind:"toolchain",name:"<fqbn>|<langage>",version,test_only,members:[{path,sha256}]}` et les octets des membres sont vérifiés par chemins relatifs/parents sans liens. Aucune commande `--version` ni installation. Preuve ≤1 MiB, membre ≤32 MiB, total membres vérifiés ≤64 MiB ; une preuve modifiée/absente/symbolique refuse l'admission. Il s'agit d'un sous-ensemble explicitement épinglé, pas de la certification de toute une installation ESP-IDF et de ses dépendances.

`provenance.json` enregistre projet/version/carte, révision catalogue, hashes des sources/policy/template, version/manifeste/membres de toolchain et preuves de bibliothèques. La version d'une bibliothèque est reprise de son `library.properties` vérifié si disponible, `unknown` sinon. **Reproductibilité limitée et cache partagé interdit restent explicites** : ces preuves ne fixent pas tout l'environnement ni la fermeture transitive des sources. La clé d'idempotence inclut projet/version/carte, payload ordonné, provenance et identité de l'adaptateur ; ce n'est pas un cache de compilation partagé entre projets/utilisateurs. Une évolution du double injecté doit changer son identité `name` pour demander une nouvelle exécution avec les mêmes autres entrées.

### Persistance, concurrence et redémarrage

```text
<root>/.build-owner.lock
<root>/build_keys/<request_sha>.json
<root>/builds/b_<uuid>/input.json
<root>/builds/b_<uuid>/provenance.json
<root>/builds/b_<uuid>/job.json
<root>/builds/b_<uuid>/live.log
<root>/builds/b_<uuid>/artifacts/<sha>.firmware[.meta.json]
<root>/builds/b_<uuid>/artifacts/<sha>.build_log[.meta.json]
```

Une lease `flock` non bloquante, avec vérification d'inode/PID, garantit un seul propriétaire compact. Le verrou global du store protège publication de la clé et transitions de job : deux starts concurrents identiques retournent le même ID et admettent une seule tâche. La tâche est une coroutine de la **même boucle**, jamais un worker/compilateur séparé. États persistés `pending` (attente de gate), `running` (slot acquis), `done`, `error`, `interrupted` ; tout état terminal conserve résultat/défauts et métadonnées d'artefacts.

Quand la lease précédente est libérée après arrêt, un nouveau propriétaire marque les anciens `pending/running` comme `interrupted`, sans inférer un firmware réussi ni relancer automatiquement. Leur log courant est publié comme artefact si le quota le permet. Un start identique reste idempotent et renvoie cet état terminal ; aucune réexécution cachée. Les admissions incomplètes non acquittées sont conservées, sans les faire passer pour des jobs réussis. `close()` annule uniquement les coroutines de tests autorisées à ce jalon et libère la lease ; une future intégration réelle devra remplacer cette fermeture par le drain/shield propriétaire documenté ci-dessus.

### Artefacts, logs et erreurs bornés

Les callbacks livrent du texte UTF-8 ; `live.log` garde la queue ≤**1 MiB d'octets**, avec `log_truncated` explicite et sans découper un caractère. À terminaison/interruption, un artefact de log **immuable** est publié. Un résultat d'adaptateur n'est réussi que s'il contient `success:true` et des octets de firmware non vides de type bin/hex/uf2/elf, ≤**32 MiB**. Les réponses contiennent uniquement IDs, tailles, types, hashes et diagnostics, jamais les octets/base64 du firmware ou des fichiers SPIFFS.

`read_artifact` comprend désormais `firmware` et `build_log`, en préservant `.vlx` et `check_report` : manifestes croisés artefact/build/projet/version, hash/taille contrôlés, parents/FD sans liens, tranches ≤12 KiB et réponse ≤24 KiB. Les octets arbitraires se lisent en base64 ; UTF-8 n'est accepté que pour une tranche valide. La vérification lit/hache le fichier entier, donc jusqu'à 32 MiB en mémoire par lecture, sans exposer un dump massif dans la réponse.

Les diagnostics sont **issus des logs** `fichier:ligne[:colonne]: severity: message` : fichier/ligne/colonne rapportés, sévérité, message borné, ID/hash du log et numéro de ligne dans le log conservé. Au plus 100 diagnostics persistés/10 retournés (moins si nécessaire pour 24 KiB), avec marqueur de troncature ; le log reste la source complète **dans sa limite de 1 MiB**. Un `source_file_hint` pour `sketch.ino.cpp` n'est qu'un indice : `line_mapping_verified:false`, aucune correspondance de ligne native n'est inventée. Les codes d'erreurs du double sont conservés dans les classes connues ou classés `compile_error`/`adapter_error`/`invalid_compiler_result`, sans transformer une exception en réussite.

Quota global **256 MiB**, commun aux snapshots/rapports/jobs/inputs/logs/firmwares ; refus net et fichiers conservés, sans purge, changement de racine/moteur ou auto-install. Le job initial réserve 8 KiB de métadonnées pour pouvoir enregistrer un échec compact même à la limite. Publication par les primitives temp/fsync/rename du store ; les artefacts peuvent rester orphelins après une interruption avant publication du job terminal et restent comptés. Aucune transaction multi-fichiers ni garantie contre un administrateur modifiant le volume n'est prétendue.

Vérifications : vrais octets factices et faux compilateurs contrôlés, v1 après v2, carte/groupe exacts, starts concurrents/idempotence, gate partagé occupé, lease exclusive, redémarrage pending/running/interrupted, erreurs et diagnostics sourcés, logs tronqués UTF-8, firmware binaire/UTF-8/hashes/quotas/liens, preuves modifiées et refus de dépendances/support/policy inconnus, absence de callback/install en intégration par défaut. Ajouter ces tests aux **59 régressions** : `python3 -m unittest discover -s test/backend/unit -p 'test_mcp_compact*.py' -q`.

## Jalon 4a — hook propriétaire ajouté, exécution offline encore bloquée

Le source du hook existe désormais : [compile.py](../../../../backend/app/api/routes/compile.py#L40) active un `RestCompileOwner` dans le **lifespan du routeur REST existant**, puis `bind_compact_offline_owner(request,user_id)` vérifie app/PID/boucle. Aucun endpoint, transport MCP, worker séparé ou configuration n'est ajouté. Un import depuis un processus MCP n'active pas ce lifespan. Une impossibilité de vérifier l'owner désactive uniquement le hook ; elle ne bloque pas le REST historique. Le chargement ASGI réel n'a pas été exécuté localement : la pile FastAPI/Pydantic n'est pas installée dans cet environnement et aucune installation n'a été faite.

Le binding de production est scellé : services réels issus du module routeur, méthodes liées à leurs classes, pas de callback compilateur arbitraire passé par un client. Les tests passent exclusivement par `RestCompileOwner.for_tests(...)`, qui impose `test_only:true` même si on tente de fournir `false`. Une liaison de production garde `test_only:false`, sans devenir ready tant que les capacités offline des services signalent des blocages. `BuildService` transmet ce mode dans job/payload/provenance/résultat, exige le même mode dans les preuves de toolchain et refuse les adaptateurs de production génériques.

Le hook reprend les résolveurs **existants** de priorité et scope, l'admission REST, `cpu_nice`, propriétaire des bibliothèques, options et SPIFFS. Une seule acquisition du même `build_queue.lane_for(...).slot(...)` ; pas de wrapper `_compile_job` qui ferait une seconde admission. Toute modification silencieuse du scope épinglé est refusée ; `scope_retry_allowed=False` empêche le scan-all de rattrapage. Les hooks privés d'admission et le binding de leur scope effectif dans la clé persistante demandent encore une validation de déploiement avant un vrai build : la voie de production reste bloquée.

Sélection interne : ESP32 appelle uniquement `espidf_compiler.compile_offline`, sans `ensure_core_for_board` ni fallback Arduino. Autres Arduino : `arduino_cli.compile_offline` exige une preuve de core déjà présent. `ToolchainInventory` accepte maintenant une preuve `arduino_core` dont ID/version et `platform.txt`/`boards.txt` sont liés aux membres locaux vérifiés ; aucun `core list/install`, library-manager ou téléchargement n'est lancé pour construire ces preuves. Ces API ne passent jamais à leur `compile` ordinaire actuellement.

**Blocage restant réel, et non contourné :**

- ESP-IDF normal : `_sync_managed_components` peut faire écrire des dépendances à télécharger pendant CMake ; `_warm_replica_in_background` peut lancer une autre préparation ; `_configure` peut supprimer/récupérer des composants corrompus et reconfigurer ; Ninja peut relancer CMake. `IDF_COMPONENT_MANAGER=0` seul ne prouverait pas que les scripts CMake transitifs et toolchains ne font plus de réseau/installation.
- Arduino normal : les recettes de plateforme et hooks de pré-build sont des commandes externes. La présence d'un core et d'un manifeste ne prouve pas que ces commandes sont offline. La résolution de scope privée doit aussi être auditée.
- Les nouvelles `offline_capabilities()` renvoient ces blocages ; `compile_offline` refuse avec `offline_guard_unavailable` **avant** le compilateur ordinaire. Core/lib/preuve manquants sont distingués et n'entraînent aucune installation. Aucune variable globale d'environnement n'a été modifiée pour prétendre isoler les sous-processus.

Le hook est donc **partiel et fail-closed**, pas une autorisation de vrai build. Lever ce dernier verrou nécessite isoler effectivement le réseau/install des exécutions transitives ou auditer leur fermeture, puis lier les preuves aux chemins SDK réellement utilisés. Reproductibilité reste limitée et cache partagé désactivé. L'inventaire prouve des fichiers/version/manifeste, jamais une fermeture transitive complète fictive.

Annulation/fermeture : le binding protège par `shield` l'ensemble admission+compilation ; une annulation client ne libère pas le slot tant que la tâche propriétaire n'est pas terminée. Le lifespan ferme l'admission et draine les tâches avant de quitter. `BuildService.close()` garde l'annulation simulant un crash pour les doubles explicites, mais attend/drain les bindings de production. Tests avec services monkeypatchés : aucun vrai compilateur ; ESP32 choisit IDF, erreurs/core/libs manquants n'installent rien, scope/priorité et mappings sont conservés, le slot survit à l'annulation jusqu'au drain. Les corps existants de compilation et les fonctions de mapping n'ont pas changé : **leurs empreintes CompilerPolicy ont été vérifiées sans ajout de whitelist**.

Procédure distante **à faire ultérieurement par le manager**, après revue et backup : [docs/mcp-compact-lxc110-review.md](../../../../docs/mcp-compact-lxc110-review.md). Rien n'a été déployé ni exécuté sur Proxmox/LXC ; aucune connexion réseau n'a eu lieu.

**STOP au jalon 4a après tests et diff ; attendre une nouvelle consigne.**

### 4b — ESP32, template approuvé et acquisition automatique interdite

`espidf_compiler.compile_offline` vérifie le hash exact du template, les sources C/C++/Arduino relatives et les preuves des chemins SDK réellement sélectionnés. Il réutilise `_compile_in_dir`, le verrou de variante et la même admission propriétaire REST ; pas de nouveau compilateur, worker ou appel HTTP. Les répertoires sont éphémères. `IDF_COMPONENT_MANAGER=0` et les options fetch déconnectées sont locaux aux sous-processus. Sync/manifest dynamique, warmup, réparation et retries CMake sont inaccessibles dans cette branche. Aucun fallback Arduino ni installation.

Les arbres de dépendances locaux sont hashés, bornés, sans liens et copiés puis revérifiés. Les recettes propres des librairies ne sont jamais copiées ; les composants managés n'acceptent qu'un `idf_component_register` littéral sans variables, commande externe ou chemin sortant. Toute autre recette est refusée, même si légitime. Les includes calculés, continuations de préprocesseur et syntaxes alternatives sont volontairement refusés. Les composants détectés doivent être présents avant compilation ; une dépendance transitive non détectée peut encore échouer à CMake. Pas de certification CMake arbitraire ni d'isolation réseau OS : SDK/core/outils locaux approuvés restent de confiance. Reproductibilité limitée et cache partagé désactivé.

Un adaptateur production `test_only:false` exige toujours le vrai owner REST et sa capacité template vérifiée ; l'inventaire et les caches sont revérifiés lors de chaque exécution. Les doubles ne peuvent pas devenir production. Hors ESP32 reste unsupported. Voir `docs/mcp-compact-lxc110-review.md` pour la preuve LXC ultérieure, non exécutée ici. Les nouveaux tests chargent l'AST réel de l'entrée avec un inner contrôlé et contrôlent les gardes internes par AST ; ils ne prouvent pas un build SDK réel. Les empreintes historiques de CompilerPolicy restent inchangées : projection du seul paramètre offline à sa valeur par défaut puis comparaison au hash original, aucune acceptation aveugle d'un nouveau hash.

### 4c — façade HTTP et image dérivée préparée

`facade.py` expose exactement six outils FastMCP sur `/mcp` dans `app.main:app`, sans importer le serveur de compatibilité. Catalogue snapshot livré avec SHA256, sans Node au runtime ; owner REST réel pour les builds, identité issue du hook REST, espaces de persistance séparés et quota global 256 MiB. Les appels build capturent leur adaptateur à l'admission. Aucun inventaire absent n'est transformé en disponibilité supposée.

Voir `docs/mcp-compact-4c-packaging.md` et `packaging/mcp-compact/` : contexte dérivé de l'image locale immuable, préimages inspectées obligatoires, nginx8002 ajouté sans modification du bloc80, entrypoint sans setup/install, conservation des bindings et volumes (y compris anonymes existants). Une différence du compilateur/template de base bloque l'overlay jusqu'à portage/revue, afin de préserver les correctifs réels. `scripts/mcp-compact-inventory.py` calcule les preuves locales de trois caches nommés et exécutables explicites ; transitive closure non prouvée. Le test ASGI utilise le vrai SDK si déjà installé, sinon est explicitement ignoré. Aucun déploiement/build réel/Qwen effectué ici.
