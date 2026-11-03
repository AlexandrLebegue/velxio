# Contrats et catalogue compact — jalon 2

Module indépendant : aucune inscription FastMCP, aucun import de `server.py`, de l'UI, du stockage ou des compilateurs. Seuls `Catalog.search_catalog` et `Catalog.get_reference` sont opérationnels. `TOOL_SCHEMAS` documente les **six** noms et leurs entrées/sorties JSON Schema ; `implemented:false` distingue les quatre contrats sans handler. Aucun `test_project`.

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

- `search_catalog(query="",kind="all",limit=5,cursor?)` : recherche de tous les mots normalisés dans noms, IDs, tags, aliases, descriptions et mots-clés réels ; ordre stable par ID. Ce classement simple ne prétend pas reproduire les poids/synonymes multilingues de l'UI. De 1 à 20 résultats ; aucun code/SVG dans les résultats. Le curseur contient révision, empreinte SHA-256 de la query normalisée, kind, offset et checksum SHA-256 ; un curseur périmé/modifié/malformé ou réutilisé sur une autre recherche est rejeté. Le checksum est une détection de cohérence publique, **pas** une signature ni une autorisation. La taille de page peut changer.
- `get_reference(id,section="overview")` : ID canonique `component:…`, `board:…` ou `example:…`. Les clés/aliases non ambigus sont acceptés ; une collision exige un ID qualifié. Sections : `overview,pins,attrs,protocol,libraries,init,limitations,sources,files,project,code`. Par défaut : résumé, broches/attributs/protocole, libs sourcées, init/limites/sources ; pour un exemple, noms, tailles/hashes des fichiers et dépendances. Ni corps de source, ni VFS, ni sourceC ou blobs embarqués par défaut. `files` est un manifeste ; `project` est débarrassé des contenus source ; **seul `code` restitue les sources d'origine**, y compris celles des groupes et chips.
- Chaque réponse sérialisée par le module est ≤**24 KiB UTF-8**. Un dépassement de section devient `quota_exceeded`, sans tronquer du code ni annoncer un faux artefact consultable. Aucun `read_artifact` n'est implémenté ici ; une grosse section pourra être servie par tranches dans un jalon ultérieur. Query ≤256 caractères, ID ≤240, curseur ≤1024 ; arguments inconnus et types invalides refusés. Les réponses restent des objets JSON ; le futur adaptateur MCP devra sérialiser sans ajouter une enveloppe illimitée.

Contrats futurs seulement :

| Nom | Entrée / résultat prévu |
| --- | --- |
| `save_project` | Création par `document` natif ; mise à jour par `project_id,expected_version` CAS et **soit** snapshot complet **soit** `changes`. Résultat : ID/version/hash, artefact `.vlx` et `download_url:null` tant qu'aucun vrai endpoint de téléchargement n'existe. L'URL future sera celle de l'artefact, sans promesse d'un projet ouvrable dans l'UI. |
| `check_project` | `project_id,version` exacts ; résultat `valid|invalid|partial`, contrôles effectués/indisponibles, résumé et artefact de diagnostic. |
| `build_project` | Exactement deux opérations : `start(project_id,version,board_id)` et `status(build_id)`. Réponses compactes avec état et métadonnées d'artefacts. Aucun autre mode. |
| `read_artifact` | ID opaque, offsets en octets, 1..12288 octets par lecture, encodage UTF-8/base64 ; taille/hash/fin/troncature explicites. |

Les modifications ciblées `changes` sont `set`/`remove` sur des JSON Pointers RFC 6901 sous `name,boards,fileGroups,folderGroups,components,wires,activeBoardId`. Pour `set`, `value` est obligatoire ; pour `remove`, il est interdit. Le futur applicateur devra décoder les échappements, refuser les chemins inexistants pour remove, permettre l'ajout d'une clé d'objet par set, remplacer uniquement un index existant d'un tableau (pas d'insertion implicite), puis valider le **document résultant** et publier un snapshot atomique après CAS. Pas de changement de format/version par patch. Ces règles ne sont pas des handlers opérationnels à ce jalon.

Le schéma du document préserve les objets internes de l'UI, dont options/SPIFFS/SD ; leur validation sémantique et le quota total de 2 MiB sont à implémenter avec le stockage futur. Une définition JSON Schema ne prétend pas déjà appliquer ce quota agrégé. Les quatre contrats ne créent ni fichier projet, ni build, ni URL et n'offrent aucun faux succès.

## Vérification et arrêt

Tests ciblés par `unittest` et validation des six schémas avec Ajv local : défaut 5, pagination exhaustive, curseurs/requête/kind/révision, reproductibilité/provenance, extraction échouant explicitement sur dépendance navigateur, aliases, pins ESP32/e-paper, dépendances réelles, absence de code par défaut sur **chaque** entrée, quotas multioctets et CAS/patch/start/status des schémas. Les tests ne compilent et ne simulent rien. Aucun fichier existant d'UI/transport/stockage/build/configuration n'est modifié.

**STOP au jalon 2 après tests et diff ; attendre une nouvelle consigne.**
