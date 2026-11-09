# Créer votre propre ligue, alignement ou monde

*[English version](../BUILD_YOUR_OWN.md)*

Tout ce que le jeu fait jouer vient d'un **monde** : un fichier SQLite construit à partir d'un **paquet de données**, un
dossier de fichiers CSV que vous pouvez modifier dans un chiffrier. Le jeu livre un monde fictif ; cette page montre comment
en faire un autre, changer un alignement ou importer des données que vous avez déjà. Chaque commande ci-dessous a été
exécutée avec cette version.

Toutes les commandes se lancent depuis le dossier du jeu.

## 1. Les façons rapides

| Vous voulez | Faites |
|---|---|
| Vos propres noms de clubs (une ville et votre nom d'équipe), sans programmer | [MAKE_YOUR_OWN_TEAMS.md](MAKE_YOUR_OWN_TEAMS.md) |
| Une autre ligue fictive | `python3 -m hs.tools.make_mock_world --out worlds/Another.db --seed 7` |
| Changer quelques joueurs ou clubs | activez le mode commissaire et utilisez Fichier > Éditeur (section 4) |
| Modifier beaucoup de joueurs dans Excel | exportez en CSV, modifiez, importez (section 4) |
| Vos propres clubs et joueurs à partir de zéro | copiez un paquet et modifiez les CSV (section 2) |
| De vrais noms à partir de vos propres données | un importateur (section 5) |

Tout fichier `.db` placé dans un dossier `worlds/` à côté de `saves/` apparaît à l'étape **Monde** d'une nouvelle carrière.

## 2. Faire une ligue à partir d'un chiffrier

Partez d'un paquet qui fonctionne. `packs/example_fictional/` compte 8 clubs ;
`python3 -m hs.tools.make_mock_league packs/my_league` en fait 32, avec contrats et plafond.

```bash
cp -r packs/example_fictional packs/my_league      # ou make_mock_league (ci-dessus)
# modifiez packs/my_league/*.csv dans un chiffrier : enregistrez en CSV, UTF-8
python3 -m hs.datapack packs/my_league             # validation : liste chaque problème avec le fichier et la ligne
python3 -m hs.tools.build_world packs/my_league packs/my_world --fictional
python3 -m hs.ingest packs/my_world worlds/My_League.db
```

`build_world` ajoute les ligues autour de la vôtre (école, junior, universitaire, Europe) avec des clubs et des joueurs
inventés. Sautez cette étape et importez le paquet directement (`python3 -m hs.ingest packs/my_league worlds/My_League.db`)
pour un monde à une seule ligue. Ensuite : **Nouvelle partie standard**, choisissez le monde à l'étape Monde, puis un club.

### Les fichiers

| Fichier | Contenu | Requis |
|---|---|---|
| `manifest.json` | nom, version, `season_start_year`, `redistributable`, `contains_real_names`, licence | oui |
| `leagues.csv` | `league_id, name, abbr, level, games_per_team` | oui |
| `teams.csv` | `team_id, league_id, name (ville), nickname, abbr, conference, division, primary_color, secondary_color, logo` | oui |
| `players.csv` | `player_id, first_name, last_name, birth_date, position (C LW RW D G), shoots, height_cm, weight_kg, nationality, team_id (vide = joueur autonome), status` | oui |
| `attributes.csv` | une ligne par joueur : cotes de 1 à 20 (patineurs et gardiens ont des ensembles différents) et `potential` | oui |
| `contracts.csv` | `player_id, team_id, start_year, years, cap_hit, contract_type, no_trade` | non |
| `rules.json` | dates de saison, format du calendrier, points, bris d'égalité, format des séries | non |
| `history/*.csv` | statistiques des saisons passées | non |

La liste complète des colonnes et des groupes de cotes se trouve dans [DATAPACK_SPEC.md](../DATAPACK_SPEC.md) ; les options
de calendrier et de séries dans [LEAGUES_AND_SCHEDULES.md](../LEAGUES_AND_SCHEDULES.md) (en anglais). Les couleurs sont au
format `#rrggbb` ; un `logo` est un chemin de fichier PNG dans le paquet.

### Conseils

* **Cotes de 1 à 20.** La ligue pour laquelle le moteur est réglé compte des joueurs en uniforme dont la moyenne est
  d'environ 10,5, avec un écart d'environ 0,7 sur la cote globale du joueur (la moyenne de ses principales cotes). Si vos
  joueurs sont beaucoup plus forts ou plus dispersés, le pointage et l'écart entre les clubs seront faussés. Vérifiez une
  saison : `python3 -m hs.sim.validate <une carrière dans votre monde> data/env_default.json --seasons 3`.
* **Un gardien a besoin des cotes de gardien, un patineur de celles de patineur.** Le validateur indique ce qui manque.
* **Chaque club a besoin de 12 attaquants, 6 défenseurs et 2 gardiens** pour jouer ; 23 ou plus est confortable.
* **Les impacts sur le plafond** devraient totaliser un peu moins que le plafond. Le plafond et le plancher sont dans
  `rules.json` et peuvent être changés avec les outils de commissaire.
* **Le nombre de matchs et le calendrier** doivent concorder : le validateur vérifie que le format du calendrier donne à
  chaque club le nombre de matchs que dit `leagues.csv`.
* **Les identifiants** sont des entiers, uniques dans leur fichier. Un joueur autonome n'a pas de `team_id`.

## 3. Un autre monde fictif, de même forme

`python3 -m hs.tools.make_mock_world --out worlds/Name.db --seed N` construit le même genre de monde à partir d'une valeur
de départ. Les noms viennent de `hs/leaguedata/fictional.py` (clubs, villes) et de `hs/worldgen.py` (noms de joueurs par
nationalité) ; modifiez ces listes pour une autre saveur. `hs/tools/make_mock_league.py` montre comment les joueurs, les
cotes et les contrats sont générés.

## 4. Modifier ce que vous avez

**Dans le jeu** : Fichier > Éditeur. Activez le mode commissaire (Paramètres, ou la commande de console `editor on`). Il
marque la sauvegarde comme modifiée pour toujours, de sorte que les réalisations et le pointage de DG l'indiquent. Ensuite :

* **Joueurs** : bio, club, statut, potentiel, contrat (impact sur le plafond, fin, clause), personnalité, chaque cote.
* **Clubs** : nom, nom d'équipe, abréviation, association, division.
* **Console** : `edit Suzuki: passing=15 cap_hit=8m team=MTL`.
* **Outils de ligue** (Ligue > Commissaire) : échanger entre n'importe quels clubs, prendre la direction de n'importe quel
  club, congédier un DG ou un entraîneur, blesser ou soigner, changer le plafond, les limites d'alignement, l'échéance,
  importer un calendrier.

**En lot, dans un chiffrier** : Fichier > Éditeur > Importer / Exporter. Exportez votre club, la ligue ou tout le monde en
CSV ; modifiez ; importez. L'importateur montre un **aperçu** (ce qui change, ce qui est nouveau, chaque problème avec sa
ligne) et n'écrit que lorsque vous appliquez. Les colonnes sont reconnues de façon souple (`DOB`, `Surname`, `Club`
fonctionnent). Une ligne sans correspondance, avec un nom, une date de naissance et un poste, crée un joueur ;
`docs/examples/new_players.csv` en est un exemple (trois nouveaux joueurs). Les colonnes et leurs alias figurent dans
[EDITOR.md](../EDITOR.md) (en anglais).

**Commencer une carrière à partir de votre monde modifié** : Fichier > Enregistrer comme départ rapide (au début d'une
saison, avant le premier match). Les nouvelles carrières peuvent partir de là. Voir [QUICKSTARTS.md](../QUICKSTARTS.md).

## 5. Importer des données que vous avez déjà

Ces outils lisent **votre copie** de données. Le jeu n'en livre aucune. Un paquet construit à partir d'elles contient les
données d'autrui : il est marqué `redistributable: false`, reste sur votre ordinateur et ne doit jamais être publié (les
dossiers `packs/`, `worlds/`, `saves/` et `save/` sont ignorés par git pour cette raison).

| Source | Commande | Notes |
|---|---|---|
| Une exportation CSV de Franchise Hockey Manager | `python3 -m hs.adapters.fhm_csv <dossier d'exportation> packs/fhm` | convertit les cotes au modèle du jeu ; les étoiles de potentiel deviennent une cote de 1 à 20 |
| Sommaires de saison MoneyPuck (`skaters_<année>.csv`, `goalies_<année>.csv`, gratuits pour usage non commercial) | `python3 -m hs.ratings.moneypuck <dossier> packs/mp --season 2025` | déduit les cotes des résultats ; ajoutez `--structure nhl_2025_26` pour les clubs et règles de la vraie ligue |
| Une exportation d'une base de données communautaire de joueurs | `python3 -m hs.adapters.db_export <dossier d'exportation> packs/db` | ou Fichier > Importer une base de données ; [DB_IMPORT.md](../DB_IMPORT.md) liste les fichiers et la correspondance |
| Un CSV de contrats (copié d'un site de plafond salarial dans un chiffrier) | `python3 -m hs.adapters.contracts_csv contracts.csv --pack packs/mp` | en-têtes souples : Player, Cap Hit, Team, Expiry |
| Carrières et repêchages passés | Fichier > Éditeur > Importer / Exporter, `career import` | [HISTORY.md](../HISTORY.md) |

Après l'une ou l'autre : `python3 -m hs.datapack packs/x`, puis `python3 -m hs.tools.build_world packs/x packs/x_world`,
puis `python3 -m hs.ingest packs/x_world worlds/X.db`. Les données MoneyPuck exigent aussi un environnement de ligue qui
leur est propre : `python3 -m hs.sim.env <dossier> --season 2025 --out save/env_2025.json` (voir `data/README.md`).

**Écrire votre propre adaptateur.** Un adaptateur est tout script qui écrit les fichiers CSV de la section 2.
`hs/adapters/fhm_csv.py` est un modèle court et lisible : lisez la source, faites correspondre ses cotes aux attributs du
moteur (`hs/attributes.py` en est la liste unique), écrivez un paquet.

## 6. Partager une ligue

Un paquet de clubs et de joueurs **inventés** peut être partagé librement : réglez `redistributable: true`,
`contains_real_names: false` et une licence dans `manifest.json`, puis compressez le dossier. Les autres le décompressent
dans `packs/`, lancent `hs.ingest` et jouent. Pour que la vôtre soit répertoriée, ouvrez un ticket « Share a league » ou
écrivez à jeremy.legere@gmail.com.

Ne partagez pas de paquets contenant de vrais joueurs, de vrais clubs, des logos ou les données d'autrui. Les vrais noms et
marques exigent généralement une licence des ligues et des associations de joueurs ; voir `THIRD_PARTY.md`.

## 7. Si quelque chose ne va pas

* `hs.datapack` affiche chaque problème avec son fichier et sa ligne. Corrigez-les tous, puis relancez.
* « No template world to start from » : construisez-en un (`python3 -m hs.tools.make_mock_world`) ou placez un monde dans
  `worlds/`.
* Pointage trop élevé ou trop bas dans votre monde : voir les conseils de la section 2 et
  [SIM_CALIBRATION.md](../SIM_CALIBRATION.md).
* Tout autre cas : [CONTRIBUTING.fr.md](../../CONTRIBUTING.fr.md) dit quoi envoyer. jeremy.legere@gmail.com.
