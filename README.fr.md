# Hockey Manager : une simulation de gestion de hockey libre

*[English version](README.md)*

**Un jeu solo de directeur général de hockey sur glace pour ordinateur.** Vous dirigez les opérations hockey d'un club de
style LNH (alignement, trios, contrats et plafond salarial, échanges, repêchage, dépistage, personnel, vestiaire,
propriétaire, finances et presse), pendant que tout un monde du hockey évolue autour de vous : clubs-écoles de type LAH et
ECHL, ligues junior, universitaire et européennes, toutes simulées match par match. Écrit en Python, avec des sauvegardes
SQLite. Aucun compte, aucun Internet, aucune publicité. Gratuit, sous licence MIT.

Si vous aimez les jeux de DG de hockey en texte et en statistiques, les modes franchise ou les simulations de gestion
sportive, voici un jeu hors ligne, modifiable, que vous pouvez lire, adapter et prolonger. Il est livré avec une **ligue
entièrement fictive** (clubs et joueurs inventés) et vous permet de **créer votre propre ligue ou votre propre
alignement à partir d'un chiffrier**.

![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue) ![licence MIT](https://img.shields.io/badge/licence-MIT-green) ![aucune dépendance](https://img.shields.io/badge/d%C3%A9pendances-aucune-lightgrey)

## Jouer en deux minutes

Il vous faut Python 3.9 ou plus récent. Rien à installer : le jeu n'utilise que la bibliothèque standard.

```bash
git clone https://github.com/jeremylegere-wq/hockey-manager.git
cd hockey-manager
./play.sh                 # Windows : double-cliquez sur PLAY_WINDOWS.bat
```

Au premier lancement, le jeu construit le monde fictif (quelques secondes) et propose d'installer un petit composant de
fenêtre (pywebview). Si vous refusez, il s'ouvre dans une fenêtre d'application Chrome, Edge ou Chromium, ou dans votre
navigateur. Ensuite : **Nouvelle partie standard**, choisissez un club et appuyez sur la barre d'espace pour jouer une
journée. Vos carrières sont enregistrées comme de simples fichiers `.db` dans `saves/`.

Pas de fenêtre ? `python3 -m hs.ui.server --saves saves --template auto --open` sert le même jeu à votre navigateur.

Le jeu parle français : **Fichier > Français (Québec)**.

Nouveau ? Lisez **[le manuel du joueur](docs/fr/MANUAL.md)** (une liste de vérification pour la première saison se trouve à
la fin).

## Ce que vous pouvez faire

* **Diriger le club.** Alignement, profondeur, trios par listes de priorité, unités d'avantage et de désavantage
  numérique, règles de départs du gardien, douze réglages tactiques avec contre-mesures, douze rôles tactiques avec cote
  d'adéquation, chimie des trios.
* **Gérer les contrats et le plafond.** Plafond et plancher, contrats d'entrée, joueurs autonomes avec et sans restriction,
  offres qualificatives, arbitrage, offres hypothécaires, rachats de contrat, salaire retenu, liste des blessés de longue
  durée, ballottage, clauses de non-échange et négociations avec les agents.
* **Échanger.** Transactions à deux ou trois clubs, choix et choix conditionnels, salaire retenu, rumeurs, date limite des
  échanges, et des clubs contrôlés par l'ordinateur qui échangent entre eux.
* **Repêcher, dépister et développer.** Un réseau de dépisteurs par région, listes du Service de recrutement, repêchage
  simulé, salle du repêchage avec chronomètre, espoirs, orientation de l'entraînement, mentors, joueurs qui progressent en
  cours de saison, recrutement universitaire.
* **Vivre dans un monde de hockey complet.** 13 ligues jouent de vraies saisons autour de vous ; hockey international,
  repêchages d'expansion, livre des records, trophées, Temple de la renommée et pointage de votre héritage de carrière.
* **Rendre des comptes au propriétaire.** Confiance du conseil, ultimatums, directives, objectifs du propriétaire avec
  échéances, bilans financiers trimestriels.
* **Gérer l'argent.** Recettes aux guichets et prix des billets, commanditaires, budgets, plan comptable avec état des
  résultats, budget par rapport au réel et à l'an dernier, état des flux de trésorerie, rénovations et nouvel aréna payé
  par le propriétaire et par un emprunt.
* **Être une personne, pas un menu.** Votre propre DG (cotes, réputation, départ sans emploi, marché de l'emploi),
  personnel, DG adjoint, moral, clans, capitainerie, conférences de presse, fil de nouvelles, attributs cachés et
  personnalités des joueurs.
* **Regarder les matchs.** Reprise 2D de chaque match (tous les joueurs et la rondelle), feuilles de pointage, résumés,
  analytique (buts attendus, Corsi, qualité des tirs), journaux de matchs et pages de saison.
* **Faire le jeu à votre main.** Créez une ligue dans un chiffrier, modifiez n'importe quel joueur ou club, importez et
  exportez en CSV, outils de commissaire, importation de calendrier, vos propres logos, départs rapides, mode défi,
  interface en français québécois.

Liste complète des fonctions par version : [docs/ROADMAP.md](docs/ROADMAP.md) (en anglais). Une page par système se
trouve dans [docs/](docs/) (en anglais).

## Le monde fictif

Rien de réel n'est livré avec le jeu. Le monde fictif (`python -m hs.tools.make_mock_world`) est généré à partir d'une
valeur de départ (« seed ») :

| | |
|---|---|
| Ligue élite | la Premier Hockey League : 32 clubs inventés, 2 associations, 4 divisions, plafond salarial, saison de 84 matchs, séries au meilleur de sept |
| Autour | ligues-écoles de type LAH et ECHL (un club affilié par équipe), trois ligues juniors majeures, une ligue universitaire, six ligues européennes |
| Gens | environ 8 000 joueurs générés avec une quarantaine de cotes, personnalités, potentiel et courbes de développement ; classes de repêchage et droits de repêchage |
| Réalisme | calibré sur le scoring réel : environ 5,7 buts, 28 tirs et 6,9 pénalités par match ; écart d'environ 0,6 but par match entre les clubs |

Utilisez `--seed N` pour une autre ligue. La même valeur donne le même monde.

## Créez votre propre ligue ou votre propre alignement

Vous n'êtes pas obligé de jouer dans le monde fictif.

**La façon la plus simple :** inscrivez vos 32 clubs dans un chiffrier (une vraie ville et votre propre nom d'équipe,
comme les Royals de Toronto) et le jeu construit la ligue : **[docs/fr/MAKE_YOUR_OWN_TEAMS.md](docs/fr/MAKE_YOUR_OWN_TEAMS.md)**.

* **À partir d'un chiffrier :** copiez `packs/example_fictional/`, modifiez les CSV, validez, construisez.
* **Changer un alignement :** activez le mode commissaire et modifiez n'importe quel joueur ou club dans le jeu, ou
  exportez les joueurs en CSV, modifiez-les dans Excel et réimportez-les (avec aperçu).
  `docs/examples/new_players.csv` sert de point de départ.
* **Apporter vos propres données :** des importateurs lisent une exportation CSV de Franchise Hockey Manager, les sommaires
  de saison de MoneyPuck (les cotes en sont dérivées), l'exportation d'une base de données communautaire et un CSV de
  contrats. Il s'agit de code seulement : les données restent les vôtres, restent sur votre ordinateur et ne sont jamais
  publiées.
* **Partager une ligue fictive :** un paquet de clubs et de joueurs inventés peut être publié sous la licence de votre choix.

Toutes les commandes, une à une : **[docs/fr/BUILD_YOUR_OWN.md](docs/fr/BUILD_YOUR_OWN.md)**.

## Documentation

| | |
|---|---|
| [docs/fr/MANUAL.md](docs/fr/MANUAL.md) | Manuel du joueur : commencer une carrière, une saison, chaque secteur du jeu, conseils, foire aux questions |
| [docs/fr/MAKE_YOUR_OWN_TEAMS.md](docs/fr/MAKE_YOUR_OWN_TEAMS.md) | Nommez vos 32 clubs dans un chiffrier, construisez la ligue, importez des alignements d'autres jeux |
| [docs/fr/BUILD_YOUR_OWN.md](docs/fr/BUILD_YOUR_OWN.md) | Créer votre ligue ou votre alignement, importer des données, partager des paquets |
| [docs/ALGORITHMS.md](docs/ALGORITHMS.md) | Les mathématiques derrière chaque IA (en anglais) |
| [docs/DATAPACK_SPEC.md](docs/DATAPACK_SPEC.md) | Le format des paquets de données (en anglais) |
| [docs/SIM_CALIBRATION.md](docs/SIM_CALIBRATION.md) | Le calibrage du moteur de match (en anglais) |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Ce qui existe, ce qui s'en vient (en anglais) |

## Signaler un bogue

Les bogues font progresser le projet. Écrivez à **jeremy.legere@gmail.com** ou ouvrez un ticket sur GitHub. Dans le jeu,
**Aide > Signaler un bogue** inscrit votre version, votre système et votre écran, puis ouvre un courriel. Indiquez ce que
vous avez fait, ce que vous attendiez, ce qui s'est produit et, s'il s'agit d'une carrière, le fichier de sauvegarde de
`saves/` (un simple fichier `.db` qui ne contient que cette carrière). Un « Traceback » dans le terminal est ce qu'il y a
de plus utile. Détails : [CONTRIBUTING.fr.md](CONTRIBUTING.fr.md).

## Pour les développeurs

Bibliothèque standard seulement (Python 3.9+), sauvegardes SQLite, serveur HTTP de la bibliothèque standard et JavaScript
natif sans étape de compilation. Le même `hs.game.cli.CLI` pilote le terminal et l'interface : chaque action est une ligne
de commande, et le jeu n'a qu'un seul ensemble de règles.

```bash
python3 -m unittest discover -s tests        # environ 410 tests ; la suite complète prend plusieurs minutes
python3 -m hs.game.cli my.db --env data/env_default.json -c "new PHM 7" -c "sim week" -c "standings"
```

Structure : `hs/sim/` le moteur de match à valeur de départ et la patinoire 2D ; `hs/league/` calendriers, classements,
séries ; `hs/game/` le jeu jour après jour (contrats, échanges, repêchage, finances, conseil, gens) ; `hs/ui/` le serveur
et l'interface ; `hs/adapters/` et `hs/ratings/` les importateurs ; `hs/tools/` les constructeurs de monde ; `docs/` une
page par système. Même valeur de départ et mêmes commandes donnent une base de données identique.

## Crédits et licence

Conception, architecture et développement principal : Jeremy Legere. Réalisé avec des assistants de programmation par IA
sous sa direction (voir Aide > Générique). Licence MIT ([LICENSE](LICENSE)). Avis de tiers et ce que le jeu ne livre pas :
[THIRD_PARTY.md](THIRD_PARTY.md). Ceci est un projet de loisir indépendant, sans lien avec une ligue, un club, un joueur,
une association de joueurs ou un jeu commercial, et sans leur appui.

<sub>Mots-clés : jeu de gestion de hockey, simulateur de directeur général de hockey, mode franchise de style LNH, jeu de
gestion sportive hors ligne, jeu de hockey libre, simulation de hockey en Python, éditeur de base de données de hockey,
ligue de hockey personnalisée, simulateur de plafond salarial.</sub>
