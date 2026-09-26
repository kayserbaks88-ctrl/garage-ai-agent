import unittest

from trimtech.modules.staff.location import distance_metres, distance_miles


class StaffLocationTests(unittest.TestCase):
    def test_haversine_distance_is_zero_for_the_same_location(self):
        self.assertEqual(distance_metres(51.5, -0.12, 51.5, -0.12), 0)

    def test_haversine_distance_is_symmetric_and_uses_straight_line_distance(self):
        forward = distance_metres(51.5, -0.12, 51.51, -0.12)
        reverse = distance_metres(51.51, -0.12, 51.5, -0.12)
        self.assertAlmostEqual(forward, reverse, places=6)
        self.assertGreater(forward, 1000)
        self.assertLess(forward, 1200)

    def test_distance_is_converted_to_miles(self):
        one_degree_at_equator = distance_miles(0, 0, 0, 1)
        self.assertAlmostEqual(one_degree_at_equator, 69.09, delta=0.1)


if __name__ == "__main__":
    unittest.main()
