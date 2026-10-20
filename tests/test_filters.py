import json
import os
import unittest

from jobmonitor.filters import location_ok, matches

CONFIG = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json"
)


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


class LevelRuleTest(unittest.TestCase):
    def test_level_above_entry_anywhere_in_title(self):
        self.assertFalse(matches("Software Engineer II - Backend", ["software engineer"], []))
        self.assertFalse(matches("Cloud Engineer 2, Site Reliability Engineering", ["engineer"], []))
        self.assertFalse(matches("Applied Researcher 3 - Multimodal AI", ["applied researcher"], []))

    def test_early_career_titles_keep_their_level(self):
        self.assertTrue(matches("Software Engineer II - Developer Portal - New Grad", ["software engineer"], []))

    def test_level_named_by_a_keyword_is_wanted(self):
        # a source can list "engineer 2" or "researcher 2" on purpose
        self.assertTrue(matches("Software Engineer 2", ["engineer 2"], []))
        self.assertTrue(matches("Researcher 2 - Networks", ["researcher 2"], []))

    def test_other_numbers_are_not_levels(self):
        self.assertTrue(matches("Software Engineer, Level 3, Backend", ["software engineer"], []))
        self.assertTrue(matches("AI Developer Intern - 4 Months", ["developer"], []))
        self.assertTrue(matches("Software Engineer 2027", ["software engineer"], []))


class YearKeywordTest(unittest.TestCase):
    def test_year_alone_needs_technical_work(self):
        self.assertFalse(matches("Finance Intern - Corporate Accounting & Tax - Winter 2027", ["2027"], []))
        self.assertFalse(matches("Content Design Intern (Summer 2027)", ["2027"], []))
        self.assertTrue(matches("Solution Architect Student - Winter 2027", ["2027"], []))
        self.assertTrue(matches("Développeur Logiciels (Stagiaire) (l'été 2027)", ["2027"], []))

    def test_year_with_another_keyword_is_unaffected(self):
        self.assertTrue(matches("Product New Grad 2027", ["2027", "new grad"], []))


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


class RealConfigWorkTypeTest(unittest.TestCase):
    """Pins down which work types the live config lets through.

    Internships and student term positions are wanted in the feed; only
    seniority, co-op and PhD titles are filtered out. Every title here is a
    real posting the feed has seen.
    """

    @classmethod
    def setUpClass(cls):
        with open(CONFIG) as f:
            config = json.load(f)
        cls.keywords = config["keywords"]
        cls.excludes = config["exclude_keywords"]

    def assertRejected(self, title):
        self.assertFalse(
            matches(title, self.keywords, self.excludes), "should be excluded: " + title
        )

    def assertKept(self, title):
        self.assertTrue(
            matches(title, self.keywords, self.excludes), "should be kept: " + title
        )

    def test_internships_and_student_terms_kept(self):
        for title in [
            "Software Engineer Intern",
            "Software Engineering Intern",
            "Summer 2027 Intern - Software Engineer",
            "Intern, Data Analytics Engineering - Winter 2027",
            "Student Researcher, BS/MS, Winter-Summer 2027",
            "2027 Winter Student Opportunities RBC Borealis - Software Developer",
            "Solution Architect Student - Winter 2027",
        ]:
            self.assertKept(title)

    def test_seniority_and_coop_still_rejected(self):
        for title in [
            "Senior Software Engineer",
            "Staff Software Engineer",
            "Software Engineer II",
            "Software Engineer II - Backend",
            "Software Engineer Co-op",  # co-op stays excluded, interns do not
            "Finance Intern - Technical Accounting & Treasury - Winter 2027",
        ]:
            self.assertRejected(title)

    def test_full_time_new_grad_kept(self):
        for title in [
            "Software Engineer, New Grad",
            "Associate Software Engineer, Early Career",
            "Software Developer, 2027 Graduate Canada",
            "New Grad 2027 (Canada)",
            "Research Engineer, Machine Learning",
        ]:
            self.assertKept(title)

    def test_intern_prefix_does_not_drop_real_roles(self):
        # a bare "intern" exclude would wrongly kill both of these
        self.assertKept("Software Engineer, Internal Tools")
        self.assertKept("Software Developer, International Payments")


if __name__ == "__main__":
    unittest.main()
