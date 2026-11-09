# Make your own teams (the easy way)

*[Version française (Québec)](fr/MAKE_YOUR_OWN_TEAMS.md)*

You can have a league that looks like the one you know, with your own club names, in about five minutes and no coding.
The game builds the players for you. Think "The Toronto Royals" and "The Montreal Reds": a real city, an invented
nickname.

## 1. What you need

* Python 3.9 or newer, and the game folder (see the README).
* A spreadsheet program (Excel, LibreOffice, Google Sheets) or any text editor.

## 2. Name your 32 clubs

1. Open **`docs/examples/my_clubs_template.csv`** in your spreadsheet program. It has 32 rows: one per club.
2. Change the `city` and `nickname` columns to what you want. Change `abbr` (three letters) if you like; leave it blank
   and the game makes one.
3. Keep the **shape**: 2 conferences, 2 divisions in each, **8 clubs in every division**, 32 in all. The schedule and
   playoffs are built for that. You can rename conferences and divisions freely (`Eastern`, `Atlantic`...), but each
   division name must be used by exactly 8 clubs.
4. Save as **CSV (UTF-8)** with a new name, for example `my_clubs.csv`. (In Excel: *Save As > CSV UTF-8*.)

| column | what to put |
|---|---|
| `city` | the place: `Toronto`, `St. Louis`, `Hamilton` |
| `nickname` | the team name: `Royals`, `Reds`, `Foundry` |
| `abbr` | three letters: `TOR`, `MTL` (optional) |
| `conference` | `Eastern` or `Western`, or your own two names |
| `division` | four names in total, two per conference |

**A note on names.** City and town names are free for anyone to use. Team nicknames, logos and colour schemes are
trademarks of the real clubs, so give your clubs their own nicknames (Royals, Reds, Foundry) and do not copy a real
club's name, crest or colours, especially if you ever share your league. Make it clearly your own league.

## 3. Build the league

Open a terminal in the game folder and run (one line):

    python3 -m hs.tools.make_mock_world --out worlds/My_League.db --clubs my_clubs.csv --name "My League"

On Windows use `py -3` instead of `python3`. If anything is wrong with your file, the message lists every problem with
its row (a missing column, 31 clubs, a division with 7 clubs, two clubs with the same name). Fix them and run it again.

Add `--seed 7` for a different set of generated players: the same seed and the same file always give the same league.

Start the game (`./play.sh`), choose **New Standard Game**, pick **My League** on the World step, then your club. The
generated players, the farm, junior, college and European leagues around you are all invented.

## 4. Change the players

Generated players have invented names. To put in your own:

* **One at a time:** File > Editor (turn on commissioner mode), then edit any name, club, contract or rating.
* **Many at once:** File > Editor > Import / Export. Export your club or the league to CSV, edit it in your
  spreadsheet, import it back. A **preview** shows what will change before anything is written.
  `docs/examples/new_players.csv` shows the columns. Details: [EDITOR.md](EDITOR.md).

Ratings are 1-20. The league is tuned for NHL-level players averaging about 10.5. Keep a typical roster near that or
scoring will drift (see [BUILD_YOUR_OWN.md](BUILD_YOUR_OWN.md), "Tips").

## 5. Bring in rosters from other games

The game does not ship anyone's data. If you own another hockey game, you can read **your own copy** of its data into
your own league, for you only.

### Franchise Hockey Manager

Export the game's CSV files, then run `python3 -m hs.adapters.fhm_csv <export folder> packs/fhm`. Step by step in
[BUILD_YOUR_OWN.md](BUILD_YOUR_OWN.md), section 5.

### The Eastside Hockey Manager editor

The community maintains a free third-party tool, the **Eastside Hockey Manager Editor**, for the modern *Eastside Hockey
Manager* game. It edits the game's database and saved games and, according to its page, imports and exports tables as
CSV, TXT, XML and Excel files. It is made by the TBL admin team at The Blue Line:
<https://ehmtheblueline.com/editor>. Read its page for setup (it warns you to back up first) and its terms; they are not
ours to state. People there also share community-made rosters. Download those from their authors, from the original
place, not from this project.

To use a roster from that tool in this game:

1. In the Editor, **export the players table** (and the clubs table if you want its clubs) to CSV or Excel.
2. Open the file in your spreadsheet program. Keep a copy of the original.
3. Make columns the importer understands: a first name, surname, birth date, position (`C LW RW D G`), club, and the
   1-20 ratings with the game's attribute names (the list is in `hs/attributes.py`; loose names such as `DOB`,
   `Surname`, `Club` are matched). Delete the columns you do not need.
4. In this game, make your league (steps 2 and 3), then File > Editor > Import / Export > **Import**, choose your file,
   and read the **preview**. It lists what matched, what is new and every row it could not use, with the reason.
5. Fix the sheet and preview again until it looks right, then **apply**.

I have not tried the tool's exports against this importer, so expect to adjust column names and scale in step 3: the
preview tells you exactly what it did not understand. The ratings in another game are on its own scale; if your league
scores too much or too little, see SIM_CALIBRATION.md.

### Anything else

A spreadsheet of players is enough. [BUILD_YOUR_OWN.md](BUILD_YOUR_OWN.md) has the column list for every file in a pack,
and "Write your own adapter" if you want to automate it.

## 6. Keep it to yourself, or share it properly

* A league of **invented** players on your own club names (steps 2-4) is yours to share. Send the `my_clubs.csv` and the
  seed, or zip the pack; others rebuild exactly the same league.
* A league that holds **real players, or data taken from another game**, is not ours or yours to share. Keep it on your
  computer. Do not upload it to GitHub, a forum, a drive or a torrent. Send people to the original tool and teach them
  to make their own with this page instead.

Trouble? jeremy.legere@gmail.com, or Help > Report a bug in the game.
