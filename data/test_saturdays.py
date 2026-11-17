import unittest

from saturdays import haversine_km, pick_saturdays


def tract(gid, score, lat, lon, km_sn=5.0):
    return {"geo_id": gid, "need_score": score, "latitude": lat, "longitude": lon,
            "km_to_safety_net": km_sn}


class PickSaturdaysTest(unittest.TestCase):
    def test_haversine_one_degree_latitude(self):
        self.assertAlmostEqual(haversine_km(33.0, -84.0, 34.0, -84.0), 111.2, delta=0.3)

    def test_picks_highest_spaced_tracts(self):
        rows = [
            tract("A", 95, 33.70, -84.40),
            tract("B", 94, 33.705, -84.40),   # ~0.6 km from A -> skipped
            tract("C", 90, 33.80, -84.40),
            tract("D", 85, 33.90, -84.40),
            tract("E", 80, 34.00, -84.40),
            tract("F", 70, 34.10, -84.40),
        ]
        out = pick_saturdays(rows)
        self.assertEqual([p["geo_id"] for p in out["picked"]], ["A", "C", "D", "E"])
        self.assertEqual([p["saturday"] for p in out["picked"]], [1, 2, 3, 4])
        self.assertEqual(out["skipped"][0]["geo_id"], "B")
        self.assertEqual(out["skipped"][0]["conflicts_with"], "A")

    def test_skips_tract_next_to_existing_safety_net(self):
        rows = [tract("A", 99, 33.7, -84.4, km_sn=0.4), tract("B", 50, 33.9, -84.4)]
        out = pick_saturdays(rows, n=1)
        self.assertEqual(out["picked"][0]["geo_id"], "B")
        self.assertIn("safety-net", out["skipped"][0]["reason"])

    def test_unscored_tracts_ignored_and_shortfall_reported(self):
        rows = [tract("A", None, 33.7, -84.4), tract("B", 60, 33.9, -84.4)]
        out = pick_saturdays(rows, n=4)
        self.assertEqual(len(out["picked"]), 1)
        self.assertEqual(out["short_of_n"], 3)

    def test_near_ties_reported(self):
        rows = [tract("A", 90, 33.7, -84.4), tract("B", 89, 34.7, -84.4),
                tract("C", 70, 35.7, -84.4)]
        out = pick_saturdays(rows, n=1)
        self.assertEqual(out["near_ties_with_last_pick"], [{"geo_id": "B", "need_score": 89}])


if __name__ == "__main__":
    unittest.main()
