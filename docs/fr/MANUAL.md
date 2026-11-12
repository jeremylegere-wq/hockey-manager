# Hockey Manager : le manuel du joueur

*[English version](../MANUAL.md)*

Vous êtes le directeur général d'un club de hockey. Vous décidez qui joue, qui est signé, échangé et repêché, ce que le
club dépense, et comment vous répondez à un propriétaire qui peut vous congédier. La ligue continue de jouer autour de
vous, que vous la regardiez ou non.

Ce manuel sert à jouer. Pour créer votre propre ligue, voir [BUILD_YOUR_OWN.md](BUILD_YOUR_OWN.md). Chaque système a une
page plus détaillée dans le dossier `docs/` (en anglais), indiquée ci-dessous. Les formules derrière les IA se trouvent
dans [ALGORITHMS.md](../ALGORITHMS.md) (en anglais).

## 1. Pour commencer

**Lancer le jeu.** `./play.sh` (macOS, Linux) ou `PLAY_WINDOWS.bat` (Windows). Python 3.9 ou plus récent est la seule
exigence. Au premier lancement, le jeu construit le monde fictif et propose d'installer pywebview pour que le jeu ait sa
propre fenêtre. Si vous refusez, il s'ouvre dans une fenêtre d'application Chrome, Edge ou Chromium, ou dans votre
navigateur. `./play.sh --no-window` saute la question.

**Passer en français.** Fichier > Français (Québec). Le choix est conservé par navigateur.

**L'écran-titre.** Continuer (votre dernière carrière), Nouvelle partie standard, Charger une partie, Paramètres,
Générique, Quitter.

**Une nouvelle carrière** se déroule ainsi (docs/SETUP.md) :

1. **Votre DG** : nom, nationalité, âge et parcours (ancien joueur, dépisteur, analytique, entraîneur, affaires). Un
   parcours donne un petit coup de pouce au départ, pas un jeu différent.
2. **Directeur** : 66 points répartis entre six cotes (négociation, jugement du talent, motivation, gestion des médias,
   entraînement, développement des jeunes), ou un modèle. Vous gagnez un point pour chaque saison complétée. Choisissez
   votre rôle (DG seulement, ou DG et entraîneur-chef), votre réputation de départ, si vous pouvez être congédié, ou
   commencez sans emploi et prenez un poste au Centre d'emploi.
3. **Monde** (si vous en avez plus d'un) : le monde fictif, ou une ligue que vous avez créée ou importée.
4. **Club** : tous les clubs par division, avec leur perspective (aspirant, à la limite, reconstruction), leur force et
   leurs meilleurs joueurs.
5. **Départ** : un nom pour la sauvegarde et une valeur de départ du monde. La même valeur et les mêmes décisions donnent
   les mêmes résultats.

Les carrières sont de simples fichiers `.db` dans `saves/`. Le jeu y écrit au fil de la partie : il n'y a pas de bouton de
sauvegarde à oublier. Copiez un fichier pour en faire une copie de secours. Des copies de secours automatiques sont
activées par défaut (Fichier > Copies de secours).

## 2. L'écran

* **Barre de menus** : Fichier, Directeur, Équipe, Ligue, Statistiques, Jouer, Aide. Boutons précédent et suivant, et
  recherche (Ctrl+F) de n'importe quel joueur, club ou membre du personnel.
* **Onglets** : Bureau, Boîte de réception, Alignement, Trios, Contrats, Échanges, Transactions, Espoirs, Dépistage,
  Personnel, Calendrier, Classement, Statistiques, Nouvelles. Tout le reste est dans les menus.
* **Barre du bas** : la date, la phase, votre fiche et la date limite des échanges. **Jour**, **Semaine**, **Prochain
  match** et **Reste de la saison** (l'été, **Prochaine phase de l'entre-saison**). **Espace** joue une journée. **Ctrl+U**
  est « Jouer jusqu'à » (une date, l'échéance, le dernier jour de la saison).
* **Clic droit sur un joueur** : son profil, son contrat, ses statistiques, la liste de surveillance, une note, ou un
  échange pour l'obtenir.
* **Chaque tableau se trie** en cliquant sur un titre de colonne et possède un bouton CSV.
* **La simulation s'arrête quand on a besoin de vous** : une blessure, un poste à combler, une offre d'échange, une
  conférence de presse, le bureau du propriétaire. Les paramètres choisissent ce qui vous interrompt.
* **Rythme de simulation** : Observer, Normal, Rapide ou Instantané, pour l'affichage des résultats du jour.

## 3. Une année dans la vie

| Quand | Ce qui se passe | Ce que vous faites |
|---|---|---|
| Fin juin | Période de resignatures : droits sur les contrats qui expirent ; vote du Temple de la renommée | Qualifier, prolonger ou laisser partir (salle des droits) |
| 1er juillet | Agents libres : la période de signature, heure par heure, dans la salle de crise | Offrir, retirer, surveiller le marché |
| Été | Repêchage (loterie, puis salle du repêchage avec chronomètre), développement, camps | Repêcher, signer des contrats d'entrée, régler l'entraînement |
| 15 septembre | Présaison, tournois d'espoirs | Fixer les trios, réduire l'alignement |
| Octobre à avril | Saison régulière : 84 matchs, ballottage, blessures, échanges entre clubs de l'ordinateur, week-end des étoiles en février | Gérer trios, échanges, presse, argent |
| Échéance | Dernier jour d'échange de la ligue | Acheter, vendre ou attendre |
| Avril à juin | Séries, trophées, bilan de saison du propriétaire | Apprendre si vous gardez votre poste |

## 4. L'alignement

* **Alignement** : attaquants, défenseurs et gardiens avec leurs principales cotes, valeur, pointage, temps de glace, moral,
  impact sur le plafond et échéance. Alignement de la LNH ou toute l'organisation, profondeur, droits de repêchage,
  contrats, blessés, liste de surveillance.
* **Les cotes** vont de 1 à 20, par groupes (techniques, mentales, physiques, gardien). La **valeur** est un seul chiffre
  qui dit la qualité actuelle d'un joueur ; le **potentiel** est son plafond. La précision du dépistage dépend de vos
  dépisteurs.
* **Ballottage et mineures** : envoyer un joueur dans les mineures peut l'exposer au ballottage (docs/WAIVERS.md). Votre
  club-école joue dans la ligue mineure ; rappelez et renvoyez à partir de l'alignement.
* **La liste des blessés de longue durée** donne un allègement du plafond lors des longues blessures (docs/LTIR.md).
* **Les fiches de joueur** montrent la valeur du contrat année par année, la personnalité, le moral et ce que le joueur
  veut.

## 5. Trios et tactiques

(docs/LINES.md, docs/TACTICS.md)

* **Trios** : quatre trios d'attaquants, trois paires de défenseurs, deux gardiens, unités d'avantage et de désavantage
  numérique, unités de prolongation. Un menu déroulant par position. **Auto** laisse l'adjoint choisir.
* **Les alignements par priorité** sont des listes ordonnées : le jeu reconstruit vos trios avant chaque match à partir de
  vos préférences, de sorte que blessures et jours de repos ne laissent pas de trou.
* **Règles de départ du gardien** : à quelle fréquence le substitut joue et quand le partant se repose.
* **Tactiques** : douze réglages (sortie de zone, zone neutre, échec-avant, couverture, avantage numérique, désavantage
  numérique) avec des contre-mesures entre les choix, un entraîneur qui en préfère certains, et une cote d'adéquation et
  d'exécution pour chacun. Le propriétaire a une identité d'équipe préférée.
* **Rôles tactiques** : douze rôles (agitateur, ombre, présence devant le filet, fusilleur, attaquant à l'échec-avant,
  bagarreur, spécialiste du désavantage numérique, défenseur de fermeture, défenseur relanceur, quart-arrière de
  l'avantage numérique, nettoyeur de zone, électron libre). Chaque joueur a une adéquation pour chaque rôle : donnez un
  rôle au bon joueur et il aide ; au mauvais et il nuit. Les clubs de l'ordinateur assignent les leurs.
* **La chimie** entre compagnons de trio et de paire se construit avec le temps ; gardez les bons trios ensemble.

## 6. Contrats et plafond

(docs/CONTRACTS.md, CONTRACT_ENGINE.md, NEGOTIATION.md, CBA_2026.md)

* Un **plafond et un plancher salariaux** s'appliquent à la masse salariale. L'espace sous le plafond figure au tableau de
  bord et à l'écran Contrats, avec une projection sur cinq ans. Une limite de 50 contrats s'applique.
* **Négociations** : ouvrez-les à partir de la page d'un joueur. Son agent a un style, une patience et une humeur ; le
  joueur a des priorités (argent, durée, rôle, clause de non-échange). Offrez un montant, une durée et des clauses ; vous
  voyez sa demande pour chaque durée et votre propre estimation de sa valeur. Une bonne cote de négociation fait baisser
  les ententes.
* **Joueurs autonomes avec restriction** : qualifiez-les, négociez ou allez en arbitrage. Les autres clubs peuvent
  soumettre des **offres hypothécaires** ; vous pouvez les égaler.
* **Contrats d'entrée**, rachats de contrat, salaire retenu et **regrets** (les contrats que vous annuleriez).
* Les règles suivent la convention collective de 2026 telle que résumée à partir de sources publiques (durées maximales,
  variation d'une année à l'autre, minimums, offres qualificatives). Ce ne sont pas des conseils juridiques et ce n'est
  pas la convention.

## 7. Échanges

(docs/TRADES.md)

Construisez une transaction à l'écran Échanges : cliquez sur les joueurs et les choix de chaque côté ; deux clubs ou trois.
L'adjoint rend un verdict, et **« que faudrait-il »** demande à l'IA ce qu'elle veut pour un joueur. Les choix peuvent
être conditionnels. Le salaire peut être retenu. Les clubs de l'ordinateur échangent entre eux jusqu'à l'échéance et
pendant l'été. Les joueurs ont une valeur d'échange qui dépend de l'âge, du contrat et des besoins du club. Les offres
refusées deviennent des rumeurs que le vestiaire entend.

## 8. Dépistage, repêchage et espoirs

(docs/SCOUTING.md, DRAFT.md, DEVELOPMENT.md, COLLEGE.md)

* **Dépistage** : assignez des dépisteurs à des régions, voyez la connaissance des joueurs grandir, lisez les listes du
  Service de recrutement et le repêchage simulé. Les dépisteurs ont des biais ; votre cote de *jugement du talent* resserre
  vos estimations.
* **Le repêchage** : une loterie, puis la salle du repêchage : votre tour, votre tableau, des échanges de choix, un
  chronomètre réglable dans les paramètres.
* **Les espoirs** jouent dans les ligues juniors, universitaire, en Europe ou dans votre club-école. Signez les
  repêchés à des contrats d'entrée avant que leurs droits expirent. Certains joueurs se développent tard ; les dépisteurs
  ne le voient pas toujours.
* **Le développement** se fait pendant la saison et l'été. Il dépend de l'âge, du potentiel, du temps de glace, du niveau
  où le joueur évolue, du caractère, des mentors que vous désignez, de l'intensité et de l'orientation de
  l'entraînement, et de votre personnel de développement.
* **Universitaire** : programmes, admissibilité, recrutement et marché des joueurs autonomes universitaires.

## 9. Les gens

(docs/PEOPLE.md, MANAGEMENT.md, CAPTAINCY.md, PRESS.md)

* **Personnel** : entraîneur-chef, adjoints, dépisteurs, physiothérapeutes. Embauchez sur le marché et réglez leurs tâches.
* **Le vestiaire** : le moral et ses raisons, les promesses faites, clans et frictions, demandes d'échange. Choisissez un
  capitaine et des assistants ; l'aperçu montre l'effet de chaque choix.
* **La salle de presse** : les conférences de presse vous attendent dans la boîte de réception. Répondez une question à la
  fois ; les conséquences se voient ensuite.
* **DG adjoint** : lit votre organisation et dresse la liste des problèmes avec un bouton pour chacun ; n'agit jamais seul.
* **Attributs cachés** : ambition, loyauté, tempérament des grands matchs, propension aux blessures et plus, révélés par le
  dépistage et le temps.

## 10. Le propriétaire et le conseil

(docs/BOARD.md)

Chaque propriétaire a une personnalité (dépenses, patience, préférence pour la jeunesse ou l'analytique). La **confiance**
bouge chaque semaine et lors des bilans. Quand elle devient basse, le propriétaire lance un **ultimatum**, qui donne un
nombre de matchs et un objectif de points. Les **directives** sont des ordres permanents (« n'échangez aucun joueur de 23
ans ou moins »). **Objectifs du propriétaire** : trois par saison (acquérir un des 30 meilleurs patineurs, échanger un
contrat, embaucher un meilleur entraîneur, donner 20 matchs dans la LNH à votre meilleur espoir, gagner la série de la
saison contre un rival…), chacun avec une priorité et une échéance ; en atteindre un donne de +2 à +6 de confiance, en
rater un coûte de 2 à 7. L'écran du Conseil montre tout.

## 11. L'argent

(docs/FINANCE.md)

* **Prix et budgets** : prix des billets par type de siège, dépistage, développement, promotion. La demande dépend des
  victoires, des prix, du marché, de l'aréna et de la nouveauté.
* **États financiers** : un plan comptable (revenus, coûts des joueurs, frais d'exploitation, amortissement, intérêts) et
  un **état des résultats** par mois, trimestre ou année, comparé au budget ou à l'an dernier, avec détail de chaque
  écriture. Un **état des flux de trésorerie** et un **dossier du conseil**.
* **Le bilan trimestriel du conseil** lit vos chiffres par rapport au budget et fait bouger la confiance.
* **Aréna** : les rénovations améliorent la qualité. Un **nouvel aréna** (entre-saison seulement, une fois) coûte capacité
  × 22 000 $ × un facteur de qualité ; le propriétaire paie 20 % plus 6 % par point de son trait de dépense, le club
  emprunte le reste sur 25 ans à 5 % ; la construction prend deux saisons et donne un effet de nouveauté aux guichets qui
  s'estompe en cinq ans.

## 12. Le monde autour

* **Autres ligues** (ligue-école de type LAH, ligue de type ECHL, trois ligues juniors, universitaire, six ligues
  européennes) jouent de vraies saisons avec classements et séries. Leurs joueurs sont votre avenir.
* **Hockey international**, **expansion** (un nouveau club, un repêchage d'expansion), **discipline** (suspensions et
  amendes), le **Temple de la renommée** et votre **pointage de DG** et vos réalisations.
* **Histoire** : champions de la ligue, trophées, records, repêchages passés, pages de saison, pages de club, la carrière de
  chaque joueur.
* **Nouvelles** : manchettes, résumés, un fil social, classements de puissance et des archives.
* **Le match en 2D** : ouvrez n'importe quel match joué pour le regarder sur la patinoire : chaque joueur, la rondelle,
  les changements de trio, les avantages numériques, les buts et leurs passes. Vitesse, caméras, buts seulement, pleine
  fenêtre (docs/RINK2D.md, en anglais).

## 13. Faire le jeu à votre main

* **Paramètres** : taille de l'interface, unités, rythme de simulation, interruptions, chronomètre du repêchage, copies de
  secours, console.
* **Éditeur et mode commissaire** (Fichier > Éditeur) : modifiez n'importe quel joueur ou club, importez et exportez en
  CSV, échangez entre n'importe quels clubs, prenez la direction de n'importe quel club, fixez les règles de la ligue.
  L'activer marque la sauvegarde comme modifiée pour toujours.
* **Mode défi** et six **défis** (redressement, reconstruction, gagner maintenant, enfer du plafond, dynastie, expansion)
  avec échéances ; pas d'éditeur, simulations courtes en saison, et vous pouvez être congédié.
* **Départs rapides** : sauvegardez un monde au début d'une saison et lancez de nouvelles carrières à partir de lui.
* **Vos propres logos**, **exportation et importation du calendrier**, une **interface en français (Québec)**.
* **Console** (Fichier > Console) : n'importe quelle commande, p. ex. `sim week`, `standings`,
  `trade ABC give ... get ...`. `help` les énumère. Les commandes sont en anglais.

## 14. Votre première saison : une liste de vérification

1. Ouvrez le **Bureau** et lisez l'accueil et les objectifs du propriétaire.
2. **Alignement** : vérifiez l'espace sous le plafond, les blessures, les contrats qui expirent. Regardez la profondeur à
   chaque poste.
3. **Trios** : appuyez sur Auto, puis changez ce avec quoi vous n'êtes pas d'accord. Vérifiez les unités d'avantage et de
   désavantage numérique.
4. **Tactiques** : laissez les valeurs par défaut jusqu'à ce que vous voyiez ce que l'entraîneur aime.
5. **Personnel** : un poste vacant ? Embauchez. Un joueur mécontent ? Ouvrez sa fiche.
6. Appuyez sur **Espace** quelques fois. Lisez la boîte de réception quand le jeu s'arrête.
7. En décembre, regardez le **Classement** et le **Conseil**. La confiance du propriétaire bouge-t-elle ?
8. Avant l'échéance, décidez si vous achetez ou vendez.
9. L'été : **Droits** (contrats qui expirent), le **repêchage**, puis les **joueurs autonomes**. Réglez l'entraînement de vos
   espoirs.

## 15. Questions

**Le jeu n'ouvre pas de fenêtre.** Lancez `./play.sh --no-window`, ou
`python3 -m hs.ui.server --saves saves --template auto --open`. Sous Linux, la fenêtre exige `libxcb-cursor0`.

**« No template world » (aucun monde modèle).** Lancez `python3 -m hs.tools.make_mock_world` et recommencez.

**Puis-je utiliser de vrais joueurs et de vrais clubs ?** Seulement avec des données qui vous appartiennent et seulement
pour vous : voir BUILD_YOUR_OWN.md. Rien de réel n'est livré.

**Puis-je annuler ?** Les copies de secours automatiques (Fichier > Copies de secours) en restaurent une comme nouvelle
sauvegarde. Les carrières sont de simples fichiers ; copiez-en un avant une décision risquée.

**Un résultat me semble faux.** Ce pourrait être un bogue. Aide > Signaler un bogue, ou écrivez à
jeremy.legere@gmail.com avec le fichier de sauvegarde.
