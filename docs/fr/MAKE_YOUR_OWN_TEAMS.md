# Créer vos propres équipes (la façon facile)

*[English version](../MAKE_YOUR_OWN_TEAMS.md)*

Vous pouvez avoir une ligue qui ressemble à celle que vous connaissez, avec vos propres noms de clubs, en cinq minutes et
sans programmer. Pensez aux « Royals de Toronto » et aux « Rouges de Montréal » : une vraie ville, un nom d'équipe
inventé. Le jeu génère les joueurs pour vous.

## 1. Ce qu'il vous faut

* Python 3.9 ou plus récent, et le dossier du jeu (voir le README).
* Un chiffrier (Excel, LibreOffice, Google Sheets) ou n'importe quel éditeur de texte.

## 2. Nommez vos 32 clubs

1. Ouvrez **`docs/examples/my_clubs_template.csv`** dans votre chiffrier. Il compte 32 lignes : une par club.
2. Changez les colonnes `city` et `nickname` pour ce que vous voulez. Changez `abbr` (trois lettres) si vous le voulez ;
   laissez-la vide et le jeu en fabrique une.
3. Gardez la **forme** : 2 associations, 2 divisions dans chacune, **8 clubs dans chaque division**, 32 en tout. Le
   calendrier et les séries sont construits pour cela. Vous pouvez renommer librement les associations et les divisions
   (`Eastern`, `Atlantic`…), mais chaque nom de division doit être utilisé par exactement 8 clubs.
4. Enregistrez en **CSV (UTF-8)** sous un nouveau nom, par exemple `my_clubs.csv`. (Dans Excel : *Enregistrer sous > CSV
   UTF-8*.)

| colonne | quoi y mettre |
|---|---|
| `city` | le lieu : `Toronto`, `St. Louis`, `Hamilton` |
| `nickname` | le nom d'équipe : `Royals`, `Rouges`, `Foundry` |
| `abbr` | trois lettres : `TOR`, `MTL` (facultatif) |
| `conference` | `Eastern` ou `Western`, ou vos deux propres noms |
| `division` | quatre noms au total, deux par association |

**À propos des noms.** Les noms de villes sont libres pour tout le monde. Les noms d'équipe, logos et couleurs sont des
marques de commerce des vrais clubs : donnez donc à vos clubs leurs propres noms (Royals, Rouges, Foundry) et ne copiez
pas le nom, l'écusson ou les couleurs d'un vrai club, surtout si vous partagez un jour votre ligue. Faites-en clairement
votre ligue.

## 3. Construisez la ligue

Ouvrez un terminal dans le dossier du jeu et lancez (sur une seule ligne) :

    python3 -m hs.tools.make_mock_world --out worlds/My_League.db --clubs my_clubs.csv --name "Ma ligue"

Sous Windows, utilisez `py -3` au lieu de `python3`. Si votre fichier a un problème, le message énumère chaque problème avec
sa ligne (une colonne manquante, 31 clubs, une division de 7 clubs, deux clubs du même nom). Corrigez et relancez.

Ajoutez `--seed 7` pour un autre ensemble de joueurs générés : la même valeur de départ et le même fichier donnent toujours
la même ligue.

Lancez le jeu (`./play.sh`), choisissez **Nouvelle partie standard**, prenez **Ma ligue** à l'étape Monde, puis votre club.
Les joueurs générés, ainsi que les ligues-écoles, juniors, universitaires et européennes autour de vous, sont tous inventés.

## 4. Changer les joueurs

Les joueurs générés ont des noms inventés. Pour mettre les vôtres :

* **Un à la fois :** Fichier > Éditeur (activez le mode commissaire), puis modifiez nom, club, contrat ou cotes.
* **Plusieurs à la fois :** Fichier > Éditeur > Importer / Exporter. Exportez votre club ou la ligue en CSV, modifiez dans
  votre chiffrier, réimportez. Un **aperçu** montre ce qui va changer avant que rien ne soit écrit.
  `docs/examples/new_players.csv` montre les colonnes. Détails : [EDITOR.md](../EDITOR.md) (en anglais).

Les cotes vont de 1 à 20. La ligue est réglée pour des joueurs de niveau LNH dont la moyenne est d'environ 10,5. Gardez
un alignement typique près de cette valeur, sinon le pointage dérivera (voir [BUILD_YOUR_OWN.md](BUILD_YOUR_OWN.md),
« Conseils »).

## 5. Apporter des alignements d'autres jeux

Le jeu ne livre les données de personne. Si vous possédez un autre jeu de hockey, vous pouvez lire **votre propre copie**
de ses données dans votre propre ligue, pour vous seulement.

### Franchise Hockey Manager

Exportez les fichiers CSV du jeu, puis lancez `python3 -m hs.adapters.fhm_csv <dossier d'exportation> packs/fhm`. Pas à pas
dans [BUILD_YOUR_OWN.md](BUILD_YOUR_OWN.md), section 5.

### L'éditeur d'Eastside Hockey Manager

La communauté entretient un outil gratuit tiers, l'**Eastside Hockey Manager Editor**, pour le jeu moderne *Eastside Hockey
Manager*. Il modifie la base de données et les parties sauvegardées du jeu et, selon sa page, importe et exporte des
tables en CSV, TXT, XML et Excel. Il est l'œuvre de l'équipe d'administration de TBL, à The Blue Line :
<https://ehmtheblueline.com/editor>. Lisez sa page pour l'installation (elle vous demande de faire une copie de secours
d'abord) et ses conditions ; ce n'est pas à nous de les énoncer. On y partage aussi des alignements créés par la
communauté. Téléchargez-les auprès de leurs auteurs, à la source, et non auprès de ce projet.

Pour utiliser un alignement de cet outil dans ce jeu :

1. Dans l'éditeur, **exportez la table des joueurs** (et celle des clubs si vous voulez ses clubs) en CSV ou en Excel.
2. Ouvrez le fichier dans votre chiffrier. Gardez une copie de l'original.
3. Faites des colonnes que l'importateur comprend : un prénom, un nom, une date de naissance, un poste (`C LW RW D G`), un
   club et les cotes de 1 à 20 avec les noms d'attributs du jeu (la liste est dans `hs/attributes.py` ; des noms souples
   comme `DOB`, `Surname`, `Club` sont reconnus). Supprimez les colonnes inutiles.
4. Dans ce jeu, créez votre ligue (étapes 2 et 3), puis Fichier > Éditeur > Importer / Exporter > **Importer**, choisissez
   votre fichier et lisez l'**aperçu**. Il énumère ce qui a été reconnu, ce qui est nouveau et chaque ligne inutilisable,
   avec la raison.
5. Corrigez le chiffrier et refaites l'aperçu jusqu'à ce que ce soit bon, puis **appliquez**.

Je n'ai pas essayé les exportations de cet outil avec cet importateur ; attendez-vous à ajuster les noms de colonnes et
l'échelle à l'étape 3 : l'aperçu vous dit exactement ce qu'il n'a pas compris. Les cotes d'un autre jeu sont à sa propre
échelle ; si votre ligue marque trop ou trop peu, voir SIM_CALIBRATION.md.

### Autre chose

Un chiffrier de joueurs suffit. [BUILD_YOUR_OWN.md](BUILD_YOUR_OWN.md) donne la liste des colonnes de chaque fichier d'un
paquet, et « Écrire votre propre adaptateur » si vous voulez automatiser.

## 6. Gardez-la pour vous, ou partagez-la comme il faut

* Une ligue de joueurs **inventés** avec vos propres noms de clubs (étapes 2 à 4) peut être partagée. Envoyez votre
  `my_clubs.csv` et la valeur de départ, ou compressez le paquet ; les autres reconstruisent exactement la même ligue.
* Une ligue qui contient de **vrais joueurs, ou des données tirées d'un autre jeu**, n'est ni à nous ni à vous de la
  partager. Gardez-la sur votre ordinateur. Ne la téléversez ni sur GitHub, ni sur un forum, ni sur un disque en ligne,
  ni par torrent. Dirigez plutôt les gens vers l'outil d'origine et montrez-leur comment faire la leur avec cette page.

Un problème ? jeremy.legere@gmail.com, ou Aide > Signaler un bogue dans le jeu.
