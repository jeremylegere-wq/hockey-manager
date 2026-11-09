"""v56: the owner's goals: candidates from the club's situation, issue once a season, progress and resolution with
board confidence, the CLI."""
import io
import json
import tempfile
import unittest

from hs.game import owner_goals as OG
from hs.game.cli import CLI
from hs.game.state import get_state

from test_game import make_db
from test_sim import ENV


class GoalTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db, self.c, self.me = make_db(tmp.name)
        self.addCleanup(self.c.close)
        OG.ensure_table(self.c)
        self.day = get_state(self.c)[0]

    def _add(self, code, target, priority="medium", deadline="2027-03-01"):
        self.c.execute("INSERT INTO owner_goals (team_id, season, code, description, priority, target, issued, deadline) VALUES (?,?,?,?,?,?,?,?)",
                       (self.me, 2026, code, code, priority, json.dumps(target), self.day, deadline))
        return self.c.execute("SELECT * FROM owner_goals ORDER BY goal_id DESC LIMIT 1").fetchone()

    def test_candidates_and_issue(self):
        c, me = self.c, self.me
        cand = OG.candidates(c, me, self.day)
        self.assertTrue(cand)
        codes = {x[0] for x in cand}
        self.assertTrue(codes <= {x[0] for x in OG._CATALOGUE})
        for code, desc, target, dl, w, prio in cand:
            self.assertIn(prio, OG.REWARD)
            self.assertTrue(dl)
        got = OG.issue(c, me, self.day)
        self.assertLessEqual(len(got), OG.MAX_GOALS)
        self.assertEqual(OG.issue(c, me, self.day), [])                      # once a season
        if got:
            self.assertTrue(c.execute("SELECT 1 FROM inbox WHERE subject LIKE 'The owner%goals%'").fetchone())

    def test_shed_contract_resolves_and_moves_confidence(self):
        c, me = self.c, self.me
        pid = c.execute("SELECT player_id FROM players WHERE team_id=? AND status='active' AND position<>'G' LIMIT 1", (me,)).fetchone()[0]
        g = self._add("shed_contract", dict(player_id=pid), "high")
        self.assertEqual(OG.progress(c, g, self.day)[0], None)
        other = c.execute("SELECT team_id FROM teams WHERE team_id<>? LIMIT 1", (me,)).fetchone()[0]
        c.execute("UPDATE players SET team_id=? WHERE player_id=?", (other, pid))
        conf = c.execute("SELECT confidence FROM board WHERE team_id=?", (me,)).fetchone()
        out = OG.daily(c, self.day)
        self.assertIn(("shed_contract", "met"), out)
        r = c.execute("SELECT status, delta FROM owner_goals WHERE goal_id=?", (g["goal_id"],)).fetchone()
        self.assertEqual((r[0], r[1]), ("met", OG.REWARD["high"]))
        if conf:
            self.assertAlmostEqual(c.execute("SELECT confidence FROM board WHERE team_id=?", (me,)).fetchone()[0], min(100, conf[0] + OG.REWARD["high"]))

    def test_deadline_and_keep_goals(self):
        c, me = self.c, self.me
        g = self._add("home_wins", dict(wins=99, season_id=c.execute("SELECT season_id FROM seasons ORDER BY start_year DESC").fetchone()[0]),
                      "low", deadline=self.day)
        self.assertEqual(OG.progress(c, g, self.day)[0], "failed")
        k = self._add("keep_first", dict(year=2027), deadline="2027-04-15")
        self.assertIsNone(OG.progress(c, k, self.day)[0])
        self.assertEqual(OG.progress(c, k, "2027-04-15")[0], "met")
        y = self._add("younger", dict(age=99.0), deadline="2027-04-15")
        self.assertIsNone(OG.progress(c, y, self.day)[0])                   # judged at the deadline
        self.assertEqual(OG.progress(c, y, "2027-04-15")[0], "met")

    def test_late_issue_skips_goals_without_time(self):
        c, me = self.c, self.me
        late = "2027-04-01"
        for code, *_x, dl, w, p in OG.candidates(c, me, late):
            pass
        got = OG.issue(c, me, late)
        self.assertTrue(all(dl >= "2027-05-01" for _, _, _, dl, _, _ in got))

    def test_cli(self):
        self.c.close()
        out = io.StringIO()
        cli = CLI(self.db, ENV, out=out)
        self.addCleanup(cli.conn.close)
        cli.onecmd("goals")
        self.assertEqual(cli.status_code, 0, out.getvalue())


if __name__ == "__main__":
    unittest.main()
