# Contribuer et signaler des bogues

*[English version](CONTRIBUTING.md)*

## Signaler un bogue

Écrivez à **jeremy.legere@gmail.com** ou ouvrez un ticket sur GitHub (les modèles demandent les bonnes informations). Dans
le jeu, **Aide > Signaler un bogue** remplit les détails et ouvre un courriel.

Un rapport qui permet de corriger le problème contient :

1. **La version** (Aide > À propos, ou `hs/ui/settings.py`) et votre système (Windows, macOS, Linux ; fenêtre ou
   navigateur).
2. **Ce que vous avez fait, ce que vous attendiez, ce qui s'est produit à la place.**
3. **L'erreur exacte**, mot pour mot, ou une capture d'écran. Si le terminal d'où le jeu a démarré affiche un
   `Traceback`, collez-le en entier.
4. **Le fichier de sauvegarde**, si cela concerne une carrière : le fichier `.db` dans `saves/`. Il ne contient que cette
   carrière, et avec lui un bogue peut généralement être rejoué exactement (le jeu est à valeur de départ : même
   sauvegarde et mêmes commandes donnent le même résultat).

Veuillez ne pas envoyer de bases de données à vrais noms ni rien que vous n'avez pas le droit de partager.

Les résultats qui sonnent faux (un échange accepté par l'IA qui paraît absurde, une cote qui semble erronée, une ligue qui
marque trop) sont aussi des bogues : dites ce que vous attendiez et pourquoi.

## Suggérer une fonction

Ouvrez un ticket. `docs/ROADMAP.md` (en anglais) montre ce qui est prévu et ce qui est déjà fait ; la longue traîne y est
volontairement.

## Partager une ligue

Un paquet de clubs et de joueurs inventés est le bienvenu. Ouvrez un ticket avec le modèle « Share a league » et donnez le
lien, ou envoyez-le par courriel. Ne publiez pas de paquets construits à partir des données d'autrui (voir
`THIRD_PARTY.md`).

## Code

```bash
python3 -m unittest discover -s tests
```

* Bibliothèque standard seulement. Aucune nouvelle dépendance sans très bonne raison.
* Chaque module a une docstring qui dit ce qu'il fait et ce que valent les chiffres ; les documents de `docs/` la
  reprennent pour les joueurs.
* Une nouvelle règle reçoit un test et une ligne de documentation. Un changement qui déplace les résultats des matchs exige
  la vérification de calibrage (`docs/SIM_CALIBRATION.md`) : buts de la ligue, pénalités et écart entre les clubs doivent
  rester où ils sont.
* Chaque action de l'interface est une ligne de commande (`hs/game/cli.py`) ; l'interface n'a jamais de règles à elle.
* Gardez les vrais noms, logos et données de tiers hors du dépôt.
