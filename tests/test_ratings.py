import unittest

from hs.attributes import ALL_ATTRS
from hs.ratings.moneypuck import NEUTRAL, UNMEASURED, attributes_for, clamp_rating, corr, z_scores


class RatingMathTests(unittest.TestCase):
    def test_clamp_and_rounding(self):
        self.assertEqual([clamp_rating(x) for x in (-5, 0.4, 10.49, 10.5, 25)], [1, 1, 10, 11, 20])

    def test_shrinkage_is_half_when_exposure_equals_k(self):
        params = {("F", "hits60"): dict(mu=0.0, sd_true=2.0, k=100.0, sign=1)}
        z_full = z_scores({"hits60": (2.0 * 1e6, 1e6)}, "F", params)["hits60"]    # huge sample: no shrinkage
        z_half = z_scores({"hits60": (2.0 * 100, 100)}, "F", params)["hits60"]    # n == k: half way
        self.assertAlmostEqual(z_full, 1.0, places=3)
        self.assertAlmostEqual(z_half, 0.5, places=6)

    def test_lower_is_better_metrics_flip_sign(self):
        params = {("F", "pen60"): dict(mu=1.0, sd_true=0.5, k=0.0, sign=-1)}
        self.assertAlmostEqual(z_scores({"pen60": (2.0 * 50, 50)}, "F", params)["pen60"], -2.0)

    def test_unmeasured_attributes_are_neutral_and_all_attributes_present(self):
        row = attributes_for({"hits60": 1.0}, "F")
        self.assertEqual(set(row), set(ALL_ATTRS))
        for a in UNMEASURED:
            if a not in ("goalie_positioning",):
                self.assertTrue(row[a] in (NEUTRAL, ""), a)
        self.assertEqual(row["hitting"], clamp_rating(10.5 + 3.0))  # z=1 -> +3 rating points

    def test_corr(self):
        self.assertAlmostEqual(corr([1, 2, 3, 4], [2, 4, 6, 8]), 1.0)


if __name__ == "__main__":
    unittest.main()
