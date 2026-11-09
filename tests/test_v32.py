"""v32, phase A2: your manager. Ratings and their effects, reputation, the GM-and-coach role, cannot be fired,
starting unemployed and the job market, the assistant GM and Find Players."""
import io
import tempfile
import unittest

from hs.game import assistant as AS
from hs.game import gm as GM
from hs.game import org
from hs.game import staff as S
from hs.game.cli import CLI
from hs.game.state import get_state, user_team
from hs.ui import screens as SC

from test_game import make_db
from test_sim import ENV


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db, self.c, self.me = make_db(self.tmp.name)
        self.addCleanup(self.c.close)
        GM.create(self.c, "Tester", "CAN", "scout", 40)
        self.day = get_state(self.c)[0]


class RatingTests(Base):
    def test_pool_and_limits(self):
        with self.assertRaises(ValueError):
            GM.check_ratings(dict(negotiation=18, judging_talent=18, motivation=18, media_handling=18, coaching=4, development=4))
        with self.assertRaises(ValueError):
            GM.check_ratings(dict(negotiation=19))
        for _, r in GM.TEMPLATES.values():
            self.assertLessEqual(sum(GM.check_ratings(r).values()), GM.POOL)

    def test_effects_follow_ratings(self):
        GM.setup_manager(self.c, None, "balanced")
        sd10 = S.scout_sd(self.c, self.me)
        GM.setup_manager(self.c, None, "talent_hound")          # judging talent 17
        self.assertLess(S.scout_sd(self.c, self.me), sd10)

    def test_improve_needs_points(self):
        GM.setup_manager(self.c, None, "balanced")
        with self.assertRaises(ValueError):
            GM.improve(self.c, "negotiation")
        x = GM._extra(self.c)
        x["points"] = 1
        GM._save_extra(self.c, x)
        self.assertEqual(GM.improve(self.c, "negotiation"), 12)
        self.assertEqual(GM.settings(self.c)["points"], 0)


class RoleTests(Base):
    def test_gm_and_coach(self):
        old = S.head_coach(self.c, self.me)["staff_id"]
        GM.setup_manager(self.c, None, "tactician", role="gm_coach")
        hc = S.head_coach(self.c, self.me)
        self.assertEqual(hc["name"], "Tester")
        self.assertEqual(hc["coaching"], GM.TEMPLATES["tactician"][1]["coaching"])
        self.assertIsNone(self.c.execute("SELECT team_id FROM staff WHERE staff_id=?", (old,)).fetchone()[0])
        with self.assertRaises(ValueError):
            S.dismiss(self.c, self.me, hc["staff_id"], self.day)       # you cannot dismiss yourself
        GM.step_down_as_coach(self.c, self.day)
        self.assertIsNone(S.head_coach(self.c, self.me))


class FiringTests(Base):
    def test_cannot_be_fired(self):
        from hs.game import boardroom as BR
        GM.setup_manager(self.c, None, "balanced", unfireable=True)
        out = BR.fire_gm(self.c, self.me, self.day, "testing")
        self.assertIn("stay on", out[0])
        self.assertEqual(user_team(self.c), self.me)

    def test_fired_hands_club_to_the_ai(self):
        from hs.game import boardroom as BR
        GM.setup_manager(self.c, None, "balanced", reputation="respected")
        BR.fire_gm(self.c, self.me, self.day, "testing")
        self.assertIsNone(user_team(self.c))
        self.assertTrue(GM.unemployed(self.c))
        self.assertLess(GM.settings(self.c)["reputation"], 50)
        self.assertIn(self.me, org.vacancies(self.c))


class UnemployedTests(Base):
    def test_start_unemployed_and_get_a_job(self):
        GM.setup_manager(self.c, None, "balanced", reputation="renowned", role="gm_coach")
        x = GM._extra(self.c)
        GM.start_unemployed(self.c, self.day)
        self.c.commit()
        self.assertIsNone(user_team(self.c))
        self.assertFalse(GM.is_coach(self.c))
        m = GM.job_market(self.c)
        self.assertTrue(m["jobs"] and m["unemployed"])
        self.c.close()
        out = io.StringIO()
        cli = CLI(self.db, ENV, out=out)
        self.addCleanup(cli.conn.close)
        cli.onecmd("sim day")                                  # the world goes on
        self.assertEqual(cli.status_code, 0, out.getvalue())
        cli.onecmd("roster")
        self.assertEqual(cli.status_code, 1)                    # club screens wait for a club
        for j in m["jobs"]:
            cli.onecmd(f"apply {j['abbr']}")
            if user_team(cli.conn):
                break
        self.assertIsNotNone(user_team(cli.conn), out.getvalue())
        self.assertTrue(GM.is_coach(cli.conn))                  # the role you chose comes with you
        cli.onecmd(f"apply {m['jobs'][0]['abbr']}")
        self.assertEqual(cli.status_code, 1)                    # one job at a time

    def test_demand_by_strength(self):
        ranks = org.projected_ranks(self.c)
        best, worst = min(ranks, key=ranks.get), max(ranks, key=ranks.get)
        self.assertGreater(GM.club_demand(self.c, best, ranks), GM.club_demand(self.c, worst, ranks))
        self.assertGreater(GM._chance(80, 30), GM._chance(30, 80))


class AssistantAndFindTests(Base):
    def test_assistant_and_find(self):
        a = AS.suggestions(self.c)
        self.assertIn("items", a)
        for x in a["items"]:
            self.assertIn(x["level"], (1, 2, 3))
            self.assertTrue(x["actions"])
        self.c.execute("UPDATE players SET status='injured' WHERE team_id=? AND position='G'", (self.me,))
        a = AS.suggestions(self.c)
        self.assertTrue(any(x["area"] == "Roster" and x["level"] == 1 for x in a["items"]))
        r = SC.player_search(self.c, {"pos": "D", "age_max": "25"})
        self.assertTrue(all(x["pos"] == "D" and x["age"] <= 25 for x in r["rows"]))
        self.assertEqual([x["value"] for x in r["rows"]], sorted((x["value"] for x in r["rows"]), reverse=True))
        mine = SC.player_search(self.c, {"status": "mine"})
        self.assertTrue(all(x["team_id"] == self.me or x["team_id"] is None for x in mine["rows"]))


if __name__ == "__main__":
    unittest.main()
