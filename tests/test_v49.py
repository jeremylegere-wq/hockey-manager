"""v49: jersey numbers and the jersey-back picture."""
import tempfile
import unittest

from hs.game import numbers as NUM
from hs.game import editor as ED
from hs.game.state import get_state

from test_world import small_world


def _club(c, pid):
    return c.execute("SELECT COALESCE(club_id, team_id) FROM players WHERE player_id=?", (pid,)).fetchone()[0]


class NumberTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db, self.c, self.me = small_world(tmp.name)
        self.addCleanup(self.c.close)
        NUM.fix(self.c)

    def test_everyone_numbered_uniquely(self):
        c = self.c
        big = [r[0] for r in c.execute("SELECT club_id FROM players WHERE status<>'retired' AND club_id IS NOT NULL GROUP BY club_id "
                                       "HAVING COUNT(*) > 97")]                    # the test world's catch-all pools
        self.assertEqual(c.execute("SELECT COUNT(*) FROM players WHERE status<>'retired' AND jersey_number IS NULL AND "
                                   f"COALESCE(club_id, team_id) IS NOT NULL AND COALESCE(club_id, 0) NOT IN ({','.join(map(str, big)) or 0})").fetchone()[0], 0)
        dup = c.execute("SELECT COUNT(*) FROM (SELECT COALESCE(club_id, CASE WHEN status IN ('active','injured','ltir') THEN team_id END) cl, "
                        "jersey_number FROM players WHERE status<>'retired' AND jersey_number IS NOT NULL GROUP BY cl, jersey_number HAVING COUNT(*)>1 AND cl IS NOT NULL)").fetchone()[0]
        self.assertEqual(dup, 0)
        self.assertEqual(c.execute("SELECT COUNT(*) FROM players WHERE jersey_number NOT BETWEEN 1 AND 98").fetchone()[0], 0)
        g = c.execute("SELECT jersey_number FROM players WHERE team_id=? AND position='G' AND status='active'", (self.me,)).fetchall()
        self.assertTrue(all(r[0] in NUM.PREFERRED["G"] or r[0] < 99 for r in g))

    def test_clash_after_a_move(self):
        c = self.c
        mine = c.execute("SELECT player_id, jersey_number FROM players WHERE team_id=? AND status='active' LIMIT 1", (self.me,)).fetchone()
        other = c.execute("SELECT player_id FROM players WHERE team_id<>? AND team_id IS NOT NULL AND status='active' LIMIT 1", (self.me,)).fetchone()[0]
        c.execute("UPDATE players SET jersey_number=?, team_id=?, club_id=? WHERE player_id=?", (mine[1], self.me, self.me, other))
        NUM.fix(c, "2099-01-01")                                 # the newcomer arrived later
        self.assertEqual(c.execute("SELECT jersey_number FROM players WHERE player_id=?", (mine[0],)).fetchone()[0], mine[1])
        self.assertNotEqual(c.execute("SELECT jersey_number FROM players WHERE player_id=?", (other,)).fetchone()[0], mine[1])

    def test_change_and_swap(self):
        c = self.c
        a, b = c.execute("SELECT player_id, jersey_number FROM players WHERE team_id=? AND status='active' LIMIT 2", (self.me,)).fetchall()
        for bad in ("99", "0", "100", "x"):
            with self.assertRaises(ValueError):
                NUM.set_number(c, a[0], bad)
        with self.assertRaises(ValueError):
            NUM.set_number(c, a[0], b[1])                       # a teammate wears it
        msg = NUM.set_number(c, a[0], b[1], swap=True)
        self.assertIn("takes", msg)
        self.assertEqual(c.execute("SELECT jersey_number FROM players WHERE player_id=?", (a[0],)).fetchone()[0], b[1])
        self.assertEqual(c.execute("SELECT jersey_number FROM players WHERE player_id=?", (b[0],)).fetchone()[0], a[1])
        free = next(n for n in range(2, 99) if n not in NUM.taken(c, _club(c, a[0])))
        NUM.set_number(c, a[0], free)
        other = c.execute("SELECT player_id FROM players WHERE team_id<>? AND team_id IS NOT NULL AND status='active' LIMIT 1", (self.me,)).fetchone()[0]
        with self.assertRaises(ValueError):
            NUM.set_number(c, other, 50)                        # not yours
        ED.set_enabled(c, True)
        NUM.set_number(c, other, next(n for n in range(2, 99) if n not in NUM.taken(c, _club(c, other))))

    def test_retire(self):
        c = self.c
        p = c.execute("SELECT player_id, jersey_number FROM players WHERE team_id=? AND status='active' LIMIT 1", (self.me,)).fetchone()
        with self.assertRaises(ValueError):
            NUM.retire(c, self.me, 77, p[0])                    # not enough games
        c.execute("INSERT INTO skater_season_stats (player_id, season_start_year, team_id, league_id, split, gp, g, a) VALUES (?,2010,?,1,'RS',320,50,90)",
                  (p[0], self.me))
        NUM.retire(c, self.me, 77, p[0])
        with self.assertRaises(ValueError):
            NUM.retire(c, self.me, 77, p[0])
        q = c.execute("SELECT player_id FROM players WHERE team_id=? AND status='active' AND player_id<>? LIMIT 1", (self.me, p[0])).fetchone()[0]
        with self.assertRaises(ValueError):
            NUM.set_number(c, q, 77)
        self.assertEqual(NUM.retired_list(c, self.me)[0]["number"], 77)

    def test_jersey_picture(self):
        c = self.c
        p = c.execute("SELECT player_id, last_name, jersey_number FROM players WHERE team_id=? AND status='active' LIMIT 1", (self.me,)).fetchone()
        svg = NUM.jersey_svg(c, p[0])
        self.assertTrue(svg.startswith("<svg"))
        self.assertIn(f">{p[2]}<", svg)
        self.assertIn(p[1].upper()[:8].replace("&", "&amp;").replace("'", "&#x27;"), svg)


if __name__ == "__main__":
    unittest.main()
