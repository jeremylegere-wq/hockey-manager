"""v36, phase E: the scouting network (knowledge levels, assignments, decay, watch list, trips), knowledge reaching
your projections, central scouting's lists, the mock draft and suggestions, training focus and variable potential."""
import datetime
import random
import statistics
import tempfile
import unittest

from hs.game import scout_net as SN
from hs.game import scouting as S
from hs.game import training as TR
from hs.game.draft import draft_year, eligible_rows
from hs.game.state import get_state
from hs.worldgen import apply_change

from test_world import small_world


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db, self.c, self.me = small_world(self.tmp.name)
        self.addCleanup(self.c.close)
        self.day = get_state(self.c)[0]
        SN.ensure_tables(self.c)


class NetworkTests(Base):
    def test_levels_and_decay(self):
        self.assertEqual(SN.level_of(85), "A")
        self.assertEqual(SN.level_of(45), "C")
        self.assertEqual(SN.level_of(5), "E")
        scouts, _ = SN._scouts(self.c, self.me)
        if not scouts:
            self.skipTest("no scouts")
        for s in scouts:
            SN.assign(self.c, s["staff_id"], "chl")
        d = datetime.date.fromisoformat(self.day)
        for w in range(30):
            SN.weekly(self.c, (d + datetime.timedelta(days=7 * w)).isoformat())
        year, pool = SN._pool(self.c)
        lv = SN.levels(self.c, [x["pid"] for x in pool])
        chl = [lv[x["pid"]] for x in pool if x["region"] == "chl"]
        other = [lv[x["pid"]] for x in pool if x["region"] != "chl"]
        if chl:
            self.assertGreater(sum(l in "AB" for l in chl) / len(chl), 0.9)
        if other:
            self.assertGreater(sum(l in "DE" for l in other) / len(other), 0.5)

    def test_knowledge_sharpens_your_lens(self):
        year = draft_year(self.c)
        pool = eligible_rows(self.c, year)[:200]
        for x in pool:
            self.c.execute("INSERT OR REPLACE INTO scout_knowledge VALUES (?,?,?)", (x["pid"], 95.0, self.day))
        sharp = S.Lens(self.c, self.me, year)
        err_a = [abs(sharp.view(x["pid"], x["cur"], x["age"], x["goalie"], x["nat"], x["height"]) - S.consensus(self.c, x, year)) for x in pool]
        for x in pool:
            self.c.execute("UPDATE scout_knowledge SET points=5 WHERE player_id=?", (x["pid"],))
        blur = S.Lens(self.c, self.me, year)
        err_e = [abs(blur.view(x["pid"], x["cur"], x["age"], x["goalie"], x["nat"], x["height"]) - S.consensus(self.c, x, year)) for x in pool]
        self.assertLess(statistics.fmean(err_a), statistics.fmean(err_e))

    def test_watch_trip_bureau_mock(self):
        year, pool = SN._pool(self.c)
        if not pool:
            self.skipTest("no class")
        SN.watch(self.c, pool[0]["pid"], self.day)
        self.assertTrue(SN.network_view(self.c)["watchlist"])
        scouts, director = SN._scouts(self.c, self.me)
        if scouts:
            name, st, en = SN.send(self.c, scouts[0]["staff_id"], "combine", self.day)
            SN._trips(self.c, (en + datetime.timedelta(days=1)).isoformat(), pool, scouts)
            self.assertEqual(self.c.execute("SELECT done FROM scout_trips").fetchone()[0], 1)
        SN.stage_lists(self.c, f"{year}-05-01")
        b = SN.bureau_view(self.c, "final")
        self.assertEqual(b["stages"], ["preliminary", "midterm", "final"])
        self.assertTrue(b["lists"])
        m = SN.mock_draft(self.c)
        self.assertEqual(len({x["pid"] for x in m}), len(m))
        sug = SN.suggestions(self.c)
        self.assertEqual(len({x["pid"] for x in sug["items"]}), len(sug["items"]))


class TrainingTests(Base):
    def test_focus_moves_the_shape_not_the_overall(self):
        from hs.worldgen import overall_of
        attrs = {a: 10 for a in TR.FOCUS["offence"] + TR.FOCUS["defence"] + TR.FOCUS["skating"] + TR.FOCUS["physical"] + TR.FOCUS["mental"]}
        tot_b, tot_f, off_b, off_f = [], [], [], []
        for s in range(300):
            b = apply_change(attrs, "C", 1.0, random.Random(s), 20)
            f = apply_change(attrs, "C", 1.0, random.Random(s), 20, TR.FOCUS["offence"])
            tot_b.append(overall_of(b, "C")); tot_f.append(overall_of(f, "C"))
            off_b.append(statistics.fmean(b[a] for a in TR.FOCUS["offence"])); off_f.append(statistics.fmean(f[a] for a in TR.FOCUS["offence"]))
        self.assertAlmostEqual(statistics.fmean(tot_b), statistics.fmean(tot_f), delta=0.12)
        self.assertGreater(statistics.fmean(off_f), statistics.fmean(off_b) + 0.12)

    def test_set_focus_and_drift(self):
        pid = self.c.execute("SELECT player_id FROM players WHERE team_id=? AND position<>'G' LIMIT 1", (self.me,)).fetchone()[0]
        TR.set_focus(self.c, self.me, pid, "skating")
        self.assertEqual(TR.focus_of(self.c, pid), "skating")
        with self.assertRaises(ValueError):
            TR.set_focus(self.c, self.me, pid, "reflexes")
        before = {r[0]: r[1] for r in self.c.execute("SELECT player_id, potential FROM player_dev")}
        TR.drift_potential(self.c, 2026, 1)
        after = {r[0]: r[1] for r in self.c.execute("SELECT player_id, potential FROM player_dev")}
        moved = [after[p] - before[p] for p in before if after[p] != before[p]]
        self.assertTrue(moved)
        self.assertLess(abs(statistics.fmean(moved)), 0.06)          # ceilings move, the average does not


if __name__ == "__main__":
    unittest.main()
