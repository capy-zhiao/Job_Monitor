import os
import tempfile
import unittest

from jobmonitor.state import load_seen, save_seen


class StateTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, "seen.json")

    def tearDown(self):
        self.dir.cleanup()

    def test_load_missing_returns_empty_set(self):
        self.assertEqual(load_seen(self.path), set())

    def test_save_then_load_roundtrip(self):
        save_seen(self.path, {"a", "b", "c"})
        self.assertEqual(load_seen(self.path), {"a", "b", "c"})

    def test_save_is_sorted_and_deterministic(self):
        save_seen(self.path, {"c", "a", "b"})
        with open(self.path) as f:
            first = f.read()
        save_seen(self.path, {"b", "c", "a"})
        with open(self.path) as f:
            second = f.read()
        self.assertEqual(first, second)

    def test_accepts_list_or_set(self):
        save_seen(self.path, ["x", "x", "y"])  # duplicates collapse on load
        self.assertEqual(load_seen(self.path), {"x", "y"})


if __name__ == "__main__":
    unittest.main()
