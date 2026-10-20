import json
import os
import tempfile
import unittest

from jobmonitor import cli
from jobmonitor.models import Job


class UrlKeyTest(unittest.TestCase):
    def test_same_posting_same_key(self):
        self.assertEqual(cli.url_key("https://boards.greenhouse.io/affirm/jobs/8017342003"),
                         cli.url_key("https://job-boards.greenhouse.io/affirm/jobs/8017342003/"))
        self.assertEqual(cli.url_key("https://example.com/j/1?utm_source=Simplify&ref=Simplify"),
                         cli.url_key("https://www.example.com/j/1"))

    def test_job_id_in_query_is_kept(self):
        self.assertNotEqual(cli.url_key("https://nuro.ai/careersitem?gh_jid=1"),
                            cli.url_key("https://nuro.ai/careersitem?gh_jid=2"))

    def test_empty(self):
        self.assertEqual(cli.url_key(""), "")


class DedupeByUrlTest(unittest.TestCase):
    def test_company_copy_wins_and_keeps_list_details(self):
        from_list = Job(uid="ghlist:https://job-boards.greenhouse.io/affirm/jobs/1", company="Affirm",
                        title="Software Engineer 1 New Grad", url="https://job-boards.greenhouse.io/affirm/jobs/1",
                        posted="2026-10-01", sponsors=True)
        from_company = Job(uid="greenhouse:affirm:1", company="Affirm",
                           title="Software Engineer - Early Career - SF", url="https://boards.greenhouse.io/affirm/jobs/1")
        other = Job(uid="greenhouse:affirm:2", company="Affirm", title="SWE", url="https://boards.greenhouse.io/affirm/jobs/2")
        out = cli.dedupe_by_url([from_list, from_company, other])
        self.assertEqual([j.uid for j in out], ["greenhouse:affirm:1", "greenhouse:affirm:2"])
        self.assertEqual(out[0].title, "Software Engineer - Early Career - SF")
        self.assertEqual(out[0].posted, "2026-10-01")
        self.assertTrue(out[0].sponsors)

    def test_jobs_without_url_are_kept_apart(self):
        a, b = Job(uid="x:1", company="A", title="T"), Job(uid="x:2", company="A", title="T")
        self.assertEqual(len(cli.dedupe_by_url([a, b])), 2)


class HealthTest(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.remove(self.path)

    def tearDown(self):
        if os.path.exists(self.path):
            os.remove(self.path)

    def run_once(self, day, **source):
        entry = {"name": "SAP", "ok": True, "fetched": 5, "matched": 1}
        entry.update(source)
        return cli.update_health(self.path, [entry], today=day)

    def test_failures_reported_once_after_three_runs_then_recovery(self):
        down = {"ok": False, "fetched": 0, "matched": 0, "error": "HTTP Error 404"}
        self.assertEqual(self.run_once("2026-10-20", **down), [])
        self.assertEqual(self.run_once("2026-10-20", **down), [])
        lines = self.run_once("2026-10-20", **down)
        self.assertEqual(len(lines), 1)
        self.assertIn("failed 3 runs in a row: HTTP Error 404", lines[0])
        self.assertEqual(self.run_once("2026-10-21", **down), [])  # not repeated
        self.assertEqual(self.run_once("2026-10-21"), ["✅ SAP is responding again"])

    def test_one_failure_between_successes_is_quiet(self):
        self.run_once("2026-10-20", ok=False, fetched=0, error="HTTP Error 429")
        self.assertEqual(self.run_once("2026-10-20"), [])
        self.assertEqual(self.run_once("2026-10-20", ok=False, fetched=0, error="HTTP Error 429"), [])

    def test_empty_for_three_days(self):
        self.assertEqual(self.run_once("2026-10-17", fetched=0), [])
        self.assertEqual(self.run_once("2026-10-19", fetched=0), [])
        lines = self.run_once("2026-10-20", fetched=0)
        self.assertEqual(lines, ["⚠️ SAP has returned no postings at all since 2026-10-17"])
        self.assertEqual(self.run_once("2026-10-21", fetched=0), [])
        self.assertEqual(self.run_once("2026-10-21", fetched=3), ["✅ SAP is returning postings again"])

    def test_sources_removed_from_config_are_forgotten(self):
        self.run_once("2026-10-20")
        cli.update_health(self.path, [], today="2026-10-21")
        with open(self.path) as f:
            self.assertEqual(json.load(f), {})


if __name__ == "__main__":
    unittest.main()
