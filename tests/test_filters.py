import unittest

from jobmonitor.filters import location_ok, matches


class MatchesTest(unittest.TestCase):
    def test_keyword_hit(self):
        self.assertTrue(matches("Software Engineer, New Grad", ["new grad"], []))

    def test_no_keyword(self):
        self.assertFalse(matches("Product Manager", ["engineer"], []))

    def test_case_insensitive(self):
        self.assertTrue(matches("SENIOR ENGINEER", ["engineer"], []))

    def test_exclude_wins_over_keyword(self):
        self.assertFalse(matches("Senior Software Engineer", ["engineer"], ["senior"]))

    def test_trailing_comma_lets_level_match_at_end(self):
        # "engineer i," should match a title that ends in "Engineer I"
        self.assertTrue(matches("IT Developer I", ["developer i,"], []))
        # ...but not "Engineer II", which the comma boundary keeps separate
        self.assertFalse(matches("Software Engineer II", ["engineer i,"], []))

    def test_empty_keywords_never_matches(self):
        self.assertFalse(matches("Anything", [], []))


class LocationOkTest(unittest.TestCase):
    def test_empty_wanted_allows_anything(self):
        self.assertTrue(location_ok("Bengaluru, IND", []))
        self.assertTrue(location_ok("Anywhere", None))

    def test_match_city(self):
        self.assertTrue(location_ok("Toronto, Ontario", ["toronto", "vancouver"]))

    def test_no_match(self):
        self.assertFalse(location_ok("Seattle, WA", ["toronto", "canada"]))

    def test_case_insensitive(self):
        self.assertTrue(location_ok("REMOTE CANADA", ["canada"]))

    def test_none_location_is_safe(self):
        self.assertFalse(location_ok(None, ["toronto"]))


if __name__ == "__main__":
    unittest.main()
