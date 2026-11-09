# Captaincy and the leadership group (hs/game/captaincy.py)

Naming a captain and two alternates is not made in a vacuum: the room, the owner and the media react.

the media all react to.

preview() says what will happen before you commit; apply() does it. What moves:
  * The room's choice: every player ranks the leaders by leadership x2 + professionalism + experience + standing
    (hs.game.people.choose_leaders' score). Naming the room's own top three costs nothing; every pick from outside it
    costs cohesion (3 for the captain, 1.5 for an alternate) and the veteran passed over loses 3 trust in you.
  * A new captain: +6 morale, +5 trust; his leadership sets the room's leadership strength.
  * Losing the C: trust -(6 + 1.2 per point of ego over 10), role -4, morale -5; an ego-driven player (15+) with
    little loyalty (8 or less) may ask for a trade (chance 15% + 4% per ego point over 15). Losing an A: half that.
  * Mid-season changes unsettle the room: -2 cohesion more than in the preseason or summer.
  * The owner: +1.5 board confidence for a captain 24 or younger if he prefers youth (7+); -1.5 for stripping a
    franchise veteran (value 60+, 28+) if he is involved (6+); +0.5 for the room's own choice.
Every change makes news (a headline, posts from the insider and the fans), lands in your inbox (the head coach's view
and any reaction), and puts a press conference in the press room (hs.game.press).

## In the UI
**Leadership group** (dashboard Locker room panel, or a player's profile) opens the picker: the current C and As, three
dropdowns with each player's leadership and room score, and a live preview of who gains and who loses, the cohesion and
board change and any trade-request risk. The button names who you are replacing ("Name X captain (replacing Y)") and asks
once more before announcing. Afterwards: the news headline, posts, the head coach's memo in the inbox and a press conference.

## CLI
`leaders <captain>, <alternate>, <alternate>` (ids or names). `captain <p>` still works and goes through the same code.
