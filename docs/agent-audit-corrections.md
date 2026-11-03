# Audit de l’agent intégré : interface, étapes et connexions

Base inspectée : commit `7bd2fc6`. Inspection du code, reproduction du flux d’événements et vérifications dans Chromium sur le serveur de développement local. Les constats et propositions ci-dessous décrivent l’état initial ; les corrections ont ensuite été appliquées après validation.

## Corrections appliquées et vérifiées — 3 novembre 2026

- Interface reliée à i18next : anglais sur le site anglais, français sur le site français, fallback anglais pour les autres langues. Dock et paramètres utilisent les tokens du workbench, dans les thèmes clair et sombre.
- Parties `reasoning` et `text` séparées dès la collecte. Les balises `<think>` en texte sont traitées sans activer le HTML brut. Le raisonnement exposé par le fournisseur est dans un bloc repliable.
- Actions identifiées, statuts métier, durées, détails et erreurs conservés dans des tours persistés. Les deux appels au même outil restent deux étapes ; l’historique reste attaché au bon message après limitation du stockage.
- Valeurs par défaut des fils normalisées avant calcul de révision. Validation des pins réelles, avec les propriétés du candidat, avant sauvegarde et application. Les aliases sont convertis en noms de pads réels, puis ces noms sont conservés côté serveur et utilisés par les moteurs.
- Composants et fils remplacés dans une seule mutation du store. Attente bornée des pads montés, recalcul de la géométrie et synchronisation du solveur. Échec de validation : circuit actif conservé. Déconnexion pendant l’application : retour du snapshot serveur précédent.
- Outils `connect_pins`, `disconnect_wire` et `set_component_properties` ajoutés au MCP privé de l’agent ; ils traversent la même validation. Un ancien fil dont la broche est connue comme invalide apparaît en pointillés rouges avec un diagnostic localisé.

Validation : 18 tests backend et 28 tests frontend ciblés réussis ; intégration avec le vrai OpenCode 1.19.3 réussie. Dans Chromium, la fixture demande d’abord une broche inexistante, puis reconnecte réellement la LED au pin 12 avec un fil sans coordonnées, couleur ni waypoints. La première demande est refusée ; la seconde est appliquée ; la LED s’allume et l’observation retourne `42` sur la série. Le dernier passage effectue une compilation AVR fraîche : firmware Uno de 1 962 octets, avec Arduino CLI 1.5.1 et le core AVR 1.8.6. Le modèle est une fixture déterministe, pas une mesure de fiabilité de tous les LLM.

Le même parcours vérifie les six étapes après rechargement, l’ouverture du thinking au clavier, le thème clair, les paramètres en français et le panneau sur une largeur de 390 px. Aucun `pageerror` JavaScript ni erreur du panneau. Les tests couvrent aussi le refus d’une broche dont les coordonnées semblent correctes, les aliases, les propriétés modifiant le pinout, le montage retardé d’un nouveau composant et le rendu d’un ancien fil invalide.

L’application atomique concerne ici le pont de l’agent. La généralisation de cette validation à tous les importeurs et la validation fonctionnelle exhaustive de chaque composant, breadboard, custom chip ou famille de carte ne sont pas démontrées par ce parcours.

## Conclusion

Les défauts signalés ont des causes identifiables. Le panneau court-circuite la traduction et une partie des tokens visuels du site. Le collecteur d’événements perd la distinction entre raisonnement exposé par le fournisseur et réponse. Le suivi d’outils ne conserve qu’un libellé éphémère.

Deux problèmes de fils ont été reproduits : un nom de broche inexistant est accepté et peut garder exactement le même tracé qu’un fil valide ; un fil minimal valide peut être refusé au lancement après que le store lui a ajouté une propriété par défaut. Ces cas montrent un défaut de contrat et de validation entre agent, affichage et simulation. Ils ne permettent pas d’affirmer que tout problème rencontré sur un circuit existant provient de la même cause.

La première validation de l’intégration couvrait surtout l’édition de code, la compilation et la série sur un circuit déjà présent. Elle ne couvrait pas suffisamment les changements de topologie ni les modèles qui émettent du raisonnement.

## 1. Constats reproduits

| Priorité | Constat | Preuve et effet |
| --- | --- | --- |
| P0 | Broche inconnue acceptée | `update_circuit` accepte `pinName="__missing_pin__"`. Dans Chromium, la broche ne correspond à aucun GPIO ni pad DOM, mais les mêmes coordonnées produisent le même chemin SVG qu’un fil valide. |
| P0 | Fil minimal refusé après application | Suppression de `color`, `waypoints` et des coordonnées d’un fil existant, en conservant ses deux endpoints valides. Le navigateur ajoute `waypoints: []`, ne résout pas les coordonnées dans ce parcours et retourne `revision_conflict`. |
| P1 | Thinking mélangé à la réponse | Deux parties amont distinctes, `reasoning` puis `text`, produisent toutes deux `message.delta`. Le frontend les concatène dans le même article Markdown. |
| P1 | Étapes écrasées et perdues | Chaque `tool.state` remplace la chaîne `activity`. À la fin du tour, cette chaîne est effacée. Les IDs de parties/appels, résultats et durées ne sont pas transmis à l’interface. |
| P1 | Langue incorrecte | Page en `lang="en"`, mais titre « Agent IA » et contrôles français. Les composants n’utilisent pas `useTranslation`. |
| P1 | Thème clair illisible | Couleur mesurée du panneau : texte `rgb(230,232,237)` sur fond `rgb(236,238,241)`. Le token `--text-primary` n’existe pas dans le thème du site ; le fallback clair reste appliqué. |

### Points d’entrée dans le code

- [AgentPanel.tsx](../frontend/src/components/agent/AgentPanel.tsx) : textes français, concaténation de `message.delta`, remplacement de `activity`, suppression du flux temporaire avant rechargement du message final.
- [AgentSettingsDialog.tsx](../frontend/src/components/agent/AgentSettingsDialog.tsx) : tous les libellés et textes d’aide sont français.
- [AgentPanel.css](../frontend/src/components/agent/AgentPanel.css) : `--text-primary`, couleurs directes, ombre et cadre indépendants du reste du workbench.
- [runtime.py](../backend/app/agent/runtime.py), `_collect` : tout delta `field="text"` est relayé sans consulter le type de la partie ; les outils perdent leur identité et leur résultat.
- [workspace.py](../backend/app/agent/workspace.py), `update_circuit` : sauvegarde avec validation structurelle, sans validation des broches.
- [projects.py](../backend/app/mcp/compact/projects.py), `validate_document` : vérifie l’existence des instances et la forme du nom de broche, pas son existence physique.
- [agentBrowserBridge.ts](../frontend/src/services/agentBrowserBridge.ts), `applyAgentSnapshot` : remplace composants et fils par des setters séparés et attend deux frames ; ce parcours ne résout pas explicitement les endpoints.
- [useSimulatorStore.ts](../frontend/src/store/useSimulatorStore.ts), `setWires` : ajoute `waypoints: []`. `loadProjectState` prévoit aussi un recalcul des positions, absent du pont de l’agent.
- [WireRenderer.tsx](../frontend/src/components/simulator/WireRenderer.tsx) : dessine le chemin et les points depuis les coordonnées, indépendamment de la validité électrique des endpoints.

Les composants demandent déjà certains recalculs à leur montage via `DynamicComponent`. C’est utile, mais cela ne constitue pas un accusé de résolution de tous les endpoints. Modifier uniquement un fil entre des composants déjà montés ne bénéficie pas nécessairement de ce montage.

## 2. Correction prioritaire du contrat de circuit

### Un fil logique, une géométrie dérivée

L’agent doit pouvoir demander une connexion avec les seules références logiques :

```json
{
  "from": { "instance_id": "uno", "pin": "13" },
  "to": { "instance_id": "resistor", "pin": "1" }
}
```

Velxio génère l’ID, les valeurs par défaut et la géométrie. Le modèle n’a pas à inventer des coordonnées de pads. Le projet `.vlx` continue de conserver positions et routes pour le rendu et l’export.

Créer une normalisation déterministe des champs optionnels **avant** calcul de révision, et l’appliquer à l’entrée du workspace comme à celle du navigateur. Au minimum, `waypoints` absent et `[]` doivent être équivalents ; une couleur absente reçoit une valeur cohérente. Les coordonnées recalculées ne doivent pas créer de conflit de révision. Conserver la détection des vraies éditions manuelles : broche changée, composant déplacé, route manuelle modifiée ou code édité.

Ajouter au MCP des opérations de connexion typées et simples (`connect_pins`, `disconnect_wire`, `set_component_properties`) au-dessus du service de projet. Les patches restent possibles pour des usages avancés, mais doivent traverser la même normalisation et validation.

### Vérifier les endpoints et expliquer les erreurs

Pour chaque connexion :

1. Résoudre l’instance et son type exact.
2. Consulter les pins documentées et les mappings de la famille de carte lorsque disponibles.
3. Valider contre les pins réelles du composant, y compris ses propriétés dynamiques et les custom chips.
4. Résoudre uniquement les aliases établis pour cette carte/composant. Le rendu et les moteurs doivent partager cette résolution ; une proximité visuelle ne crée pas une connexion.
5. Refuser une broche inconnue avec une erreur structurée donnant le fil, l’endpoint reçu et les broches valides. Une définition de pins indisponible donne un état distinct, pas un succès implicite.

Le catalogue actuel ne documente pas toutes les broches. Réutiliser le checker existant là où ses données sont connues, puis compléter par un registre de pins effectivement chargées côté navigateur. Ne pas annoncer une validation exhaustive à partir du catalogue seul.

### Appliquer le circuit en une opération cohérente

Créer un service commun d’application de circuit, utilisé par l’agent et les parcours d’hydratation, avec une option explicite de préservation de l’identité du projet sauvegardé.

Ce service :

- Vérifie la révision de départ et prépare le document normalisé.
- Attend la disponibilité des définitions et pads nécessaires, avec une attente bornée et un état `pending` explicite. Deux frames arbitraires ne sont pas un critère de disponibilité.
- Valide les endpoints avant de remplacer le circuit actif.
- Applique ensemble la nouvelle topologie dans le store du simulateur, puis recalcule les routes sans effacer les routes manuelles.
- Attend le réattachement des composants et la prise en compte de la topologie par les services de simulation avant d’autoriser le lancement.
- Retourne la révision appliquée et les diagnostics au backend.

Le backend distingue `saved`, `applied` et `validated`. `update_circuit` ne doit pas laisser croire qu’un circuit est déjà visible ou connecté lorsque seul le snapshot serveur est sauvegardé. Un échec doit conserver le dernier circuit actif valide et le candidat consultable, plutôt que produire un circuit partiellement appliqué.

Pour les anciens projets invalides, afficher un diagnostic localisé sur le fil et ses endpoints. Un marqueur « Unresolved pin » et la paire `instance:pin → instance:pin` sont plus utiles qu’un trait ordinaire dont les points semblent correctement posés.

## 3. Corriger le flux et la présentation des étapes

### Restaurer les frontières des parties

Dans le collecteur, suivre les parties par `part_id` et leur type (`text`, `reasoning`, `tool`). Router ensuite les deltas vers le bon type d’événement. Si un delta arrive avant sa définition, le garder brièvement en attente au lieu de le supposer être une réponse.

Chaque événement doit transporter les identifiants utiles : `turn_id`, `message_id`, `part_id`, et `tool_call_id` pour un outil. Les résultats d’opérations gardent leur statut propre : un appel MCP terminé avec `{ok:false}` est une action échouée, même si le transport de l’outil s’est terminé normalement.

Le cas des modèles qui placent littéralement des balises `<think>` dans une partie texte nécessite un parseur incrémental distinct, capable de traiter des balises coupées entre plusieurs chunks. Ce cas n’a pas été reproduit ici ; il doit faire partie des fixtures de compatibilité. Le rendu reste composé de composants React, sans activer globalement le HTML brut dans les messages.

### Présentation proposée

```text
User
Connect the LED to pin 13 and run the project.

Thinking                         2.1 s  ▸

✓ Read project
✓ Update circuit                 2 connections validated
✓ Compile                        Arduino Uno · 1678 bytes
✓ Start simulation               Running
✓ Observe serial                 “42”

Assistant
The simulation is running. Serial output contains 42.
```

Le bloc « Thinking » est repliable et distinct de la réponse ; il présente uniquement ce que le fournisseur expose. Aucun état de réflexion détaillé n’est inventé si le fournisseur ne l’envoie pas.

Remplacer la chaîne `activity` par une liste d’étapes identifiées avec statuts `pending`, `running`, `succeeded`, `failed`, `cancelled`. Une étape conserve son résultat succinct et ses détails repliables : fichier modifié, endpoints connectés, diagnostics, extrait de série. Les étapes restent visibles après le tour et après rechargement.

Ajouter un état de démarrage réel pendant le lancement d’OpenCode. Conserver le message en streaming jusqu’à sa finalisation, traiter `message.completed` et remplacer la partie correspondante sans vider l’affichage avant une requête de rechargement.

Le stockage conserve un résumé borné des tours et étapes ; le frontend ne dépend pas uniquement du flux SSE vivant pour reconstruire l’historique.

## 4. Intégrer le panneau au site

Utiliser `useTranslation` dans le panneau et les paramètres. Créer les clés `agent.*` dans la ressource anglaise et les traductions disponibles, avec le fallback anglais habituel. Les erreurs backend renvoient des codes traduisibles ; les diagnostics du compilateur restent affichés comme tels.

La langue de l’interface suit celle du site. La langue de conversation suit le message de l’utilisateur ; ce sont deux paramètres différents.

Réutiliser les tokens existants : `--color-fg-default`, `--color-fg-muted`, les surfaces et bordures du workbench, les couleurs d’action/état, l’espacement et les règles de focus. Supprimer le faux token `--text-primary` et les couleurs de texte fixes.

Aligner le dock sur les autres panneaux : en-tête compact, bordure de séparation, typographie et boutons d’icônes identiques, ombre et arrondis discrets. Les paramètres utilisent la présentation et la couche modale de l’application. L’éditeur possède la largeur du panneau dans son layout, au lieu de dépendre d’une modification DOM de `.app` depuis le chat. Garder un comportement adapté aux écrans étroits.

## 5. Ordre de correction et validation

| Lot | Changements | Vérification requise |
| --- | --- | --- |
| 1. Connexions et révisions | Normalisation, validation des pins, application cohérente du circuit, diagnostics | Fil minimal accepté et rendu ; pin inconnue refusée ; révision stable après géométrie ; aucune édition manuelle écrasée |
| 2. Événements | Parties typées, IDs, résultats et étapes persistés | Raisonnement séparé du texte ; deux appels au même outil restent distincts ; erreur métier affichée comme erreur ; reprise après déconnexion |
| 3. Interface | Traductions, tokens, dock, cartes d’étapes et bloc repliable | Anglais et français, thèmes clair et sombre, clavier, mobile et redimensionnement |
| 4. Parcours complet | Régression avec modification du circuit et compilation réelle | Ajouter LED/résistance, connecter les pins, lancer, vérifier le comportement du composant et la série |

Cas supplémentaires à conserver : aliases valides de pins, broches erronées avec coordonnées visuellement plausibles, composants déjà montés, nouveaux composants à montage retardé, changement de propriétés modifiant le pinout, breadboards et junctions, arrêt pendant compilation, sauvegarde/import `.vlx`, et restauration d’un tour après rechargement.

Les tests actuels de `agent-browser-bridge` remplacent le circuit par des mocks à `wires: []`. Ils doivent être complétés par une intégration réelle du store, de la résolution de pins et du rendu, puis par un cas de simulation avec résultat de composant observé. Le test initial de série seule reste utile, mais ne valide pas ce trajet des connexions.

## Livrable attendu

Une interface conversationnelle dans la langue du site, des étapes conservées et lisibles, un thinking distinct, et un circuit dont les connexions affichées correspondent aux endpoints réellement résolus. Le lancement ne doit plus échouer parce que le navigateur complète un champ optionnel, ni annoncer un câblage validé lorsqu’un nom de pin est inconnu.
