"""Integrity checks for config.json.

collect_matches() deliberately swallows per-source exceptions so one dead careers API
cannot take down the whole run. The flip side is that a typo in config.json — an unknown
"type", a missing "board" — does not fail anything either: that company just silently
stops being monitored. These tests turn those mistakes into a red CI run instead.
"""
import json
import os
import unittest
from collections import Counter

from jobmonitor.fetchers import FETCHERS

CONFIG = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.json")

# Keys each fetcher reads with source["..."] and never with source.get(...), i.e. the ones
# whose absence raises. Kept explicit rather than derived so a reviewer can read it;
# test_required_keys_cover_every_fetcher forces an update when a fetcher is added.
REQUIRED_KEYS = {
    "github_listings": ["urls"],
    "microsoft": [],
    "apple": [],
    "greenhouse": ["board"],
    "lever": ["company"],
    "ashby": ["board"],
    "amazon": [],
    "workday": ["host", "site", "tenant"],
    "phenom": ["host"],
    "eightfold": ["domain"],
    "recruitee": ["board"],
    "google": [],
    "shopify": [],
    "successfactors": ["host"],
    "icims": ["host"],
    "oracle": ["host", "site_number"],
    "pcsx": ["domain", "host"],
    "dayforce": ["company"],
    "smartrecruiters": ["company"],
    "jazzhr": ["board"],
    "ibm": [],
}


def load_config():
    with open(CONFIG) as f:
        return json.load(f)


class ConfigTest(unittest.TestCase):
    def setUp(self):
        self.cfg = load_config()          # a JSON syntax error fails every test here
        self.sources = self.cfg["sources"]

    def label(self, i, source):
        return source.get("name", "sources[%d]" % i)

    def test_top_level_shape(self):
        self.assertIsInstance(self.cfg.get("keywords"), list)
        self.assertTrue(self.cfg["keywords"], "keywords is empty: nothing would ever match")
        self.assertIsInstance(self.sources, list)
        self.assertTrue(self.sources, "no sources configured")
        for key in ("exclude_keywords", "locations"):
            if key in self.cfg:
                self.assertIsInstance(self.cfg[key], list, key)

    def test_every_source_type_has_a_fetcher(self):
        unknown = [
            "%s: type %r" % (self.label(i, s), s.get("type"))
            for i, s in enumerate(self.sources)
            if s.get("type") not in FETCHERS
        ]
        self.assertEqual(unknown, [], "unknown source types (typo?)")

    def test_every_source_has_its_required_keys(self):
        missing = []
        for i, s in enumerate(self.sources):
            for key in REQUIRED_KEYS.get(s.get("type"), []):
                if key not in s:
                    missing.append("%s (%s): missing %r" % (self.label(i, s), s["type"], key))
        self.assertEqual(missing, [])

    def test_source_names_are_unique(self):
        """Names label the log lines and error reports; a duplicate usually means a company
        was pasted in twice and is being fetched twice."""
        counts = Counter(s.get("name") for s in self.sources if "name" in s)
        dups = sorted(n for n, c in counts.items() if c > 1)
        self.assertEqual(dups, [])

    def test_per_source_overrides_are_lists(self):
        bad = [
            "%s: %s" % (self.label(i, s), key)
            for i, s in enumerate(self.sources)
            for key in ("keywords", "exclude_keywords", "locations")
            if key in s and not isinstance(s[key], list)
        ]
        self.assertEqual(bad, [], "a string here would be matched character by character")

    def test_required_keys_cover_every_fetcher(self):
        """Adding a fetcher without listing its required keys would skip validation for it."""
        self.assertEqual(sorted(REQUIRED_KEYS), sorted(FETCHERS))


if __name__ == "__main__":
    unittest.main()
