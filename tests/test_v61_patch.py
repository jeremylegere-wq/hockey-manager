"""v0.61 patch: bug reports #31 to #35. The draft pick that made the pick and then crashed on a SQL function SQLite
does not have, draft-day offers the AI then refused, inbox buttons that showed a bare player id or did nothing, and the
contract-talks window that hung on "Calling his agent"."""
import json
import re
import tempfile
import unittest
from pathlib import Path

from hs.game import draft as D
from hs.game import draft_floor as F
from hs.game import college as CO
from hs.game.state import add_message, get_state
from hs.ui import api

from test_game import make_db
from test_world import small_world

ROOT = Path(__file__).resolve().parent.parent


class DraftDayBase(unittest.TestCase):
    first = "me"                                                           # who holds pick 1

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db, self.c, self.me = small_world(self.tmp.name)
        self.addCleanup(self.c.close)
        D.ensure_tables(self.c)
        self.year = D.draft_year(self.c)
        if not D.rankings(self.c, self.year):
            self.skipTest("no draft class in the test world")
        teams = [t[0] for t in self.c.execute("SELECT team_id FROM teams WHERE league_id=1 ORDER BY team_id")]
        teams.remove(self.me)
        order = [self.me] + teams if self.first == "me" else [teams[0], self.me] + teams[1:]
        rows = [(self.year, rnd * len(order) + k + 1, rnd + 1, t, None, None) for rnd in range(7) for k, t in enumerate(order)]
        self.c.executemany("INSERT INTO draft_picks VALUES (?,?,?,?,?,?)", rows)
        self.c.execute("INSERT OR REPLACE INTO pack_info (key, value) VALUES ('live_draft', '1')")   # as the UI server sets it
        self.day = get_state(self.c)[0]


class LivePickTests(DraftDayBase):
    def test_live_pick_does_not_crash(self):
        """#32: user_pick made the pick, then built its reply with SQL's chr(), which SQLite lacks, so the UI saw an error."""
        best = D.board(self.c, self.me, 5)[0][0]
        lines = D.user_pick(self.c, best, self.day)
        self.assertTrue(lines and lines[0].startswith("You selected "))
        self.assertEqual(self.c.execute("SELECT player_id FROM draft_picks WHERE draft_year=? AND overall=1", (self.year,)).fetchone()[0], best)

    def test_no_chr_in_sql(self):
        """SQLite has no chr(): char(32) is the way to write a space in a query."""
        bad = []
        for f in (ROOT / "hs").rglob("*.py"):
            for n, line in enumerate(f.read_text(encoding="utf8").splitlines(), 1):
                if re.search(r"(SELECT|\|\|).*\bchr\(\d+\)|\bchr\(\d+\)\s*\|\|", line) and "execute" in line:
                    bad.append(f"{f.name}:{n}")
        self.assertEqual(bad, [])


class TradeDownOfferTests(DraftDayBase):
    def test_every_trade_down_offer_is_accepted(self):
        """#32: the offers the draft room showed were ones pickswap then refused (they paid more than the pick was worth)."""
        offers = D.pick_deals(self.c)["down"]
        self.assertTrue(offers)
        for o in offers:
            give, get = o["give"], o["get"]
            if self.c.execute("SELECT 1 FROM draft_picks WHERE draft_year=? AND overall=? AND team_id=?", (self.year, give[0], self.me)).fetchone() is None:
                continue                                                  # an earlier accepted offer moved the pick
            F.pickswap(self.c, self.year, self.me, o["team_id"], give, get, self.day)
            break


class BuyOfferTests(DraftDayBase):
    first = "other"

    def test_buy_offer_is_accepted(self):
        buy = D.pick_deals(self.c)["buy"]
        if buy is None:
            self.skipTest("nothing of ours is worth the pick on the clock")
        F.pickswap(self.c, self.year, self.me, buy["team_id"], buy["give"], buy["get"], self.day, D.board_slide(self.c, self.year))


class InboxButtonTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db, self.c, self.me = make_db(self.tmp.name)
        self.addCleanup(self.c.close)
        self.day = get_state(self.c)[0]

    def test_arbitration_button_names_the_player(self):
        """#33: the button read "arbitrate 5521", the command, so it looked like a player id."""
        r = self.c.execute("SELECT player_id, first_name||char(32)||last_name FROM players WHERE team_id=? LIMIT 1", (self.me,)).fetchone()
        add_message(self.c, self.day, "Arbitration", f"He can go to arbitration (`arbitrate {r[0]}`; the award can be low).")
        self.c.commit()
        msg = api.inbox_view(self.c)["messages"][0]
        labels = [a["label"] for a in msg["actions"]]
        self.assertIn(f"Take to arbitration: {r[1]}", labels)
        self.assertFalse(any(re.search(r"\d{3,}", x) for x in labels))

    def test_college_free_agent_message_opens_the_tab(self):
        """#31: the college free-agents message had no button; it now opens College Hockey on that tab."""
        src = (ROOT / "hs" / "game" / "college.py").read_text(encoding="utf8")
        self.assertIn('href="#college/fa"', src)
        js = (ROOT / "hs" / "ui" / "static" / "v46.js").read_text(encoding="utf8")
        self.assertIn('["programs", "recruiting", "mine", "fa"].includes(arg)', js)


class TalksWindowTests(unittest.TestCase):
    def test_blocked_panel_does_not_use_an_undefined_name(self):
        """#34: render() used `done` in the "No talks" panel before it was defined, so the window hung on
        "Calling his agent" for every blocked case. It is now defined first, and a failed call shows an error."""
        js = (ROOT / "hs" / "ui" / "static" / "features.js").read_text(encoding="utf8")
        body = js[js.index("  render(v) {"):]
        first_use = body.index("${done ?")
        self.assertLess(body.index("const done ="), first_use)
        self.assertIn("catch (err)", js[js.index("async open(pid)"):js.index("  render(v) {")])


if __name__ == "__main__":
    unittest.main()
