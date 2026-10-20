import json
import os
import tempfile
import unittest

from jobmonitor import cli, logos
from jobmonitor.models import Job

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


class LogosTest(unittest.TestCase):
    def test_base_company_drops_source_suffix(self):
        self.assertEqual(logos.base_company("TD (Security)"), "TD")
        self.assertEqual(logos.base_company("Cerebras (US new grad)"), "Cerebras")
        self.assertEqual(logos.base_company("Otter.ai"), "Otter.ai")

    def test_fetches_only_missing_icons_and_skips_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "td.com.png"), "wb") as f:
                f.write(PNG)
            asked = []

            def fake_fetch(domain):
                asked.append(domain)
                return (b"\xff\xd8\xff" + b"\x00" * 8, ".jpg") if domain == "meta.com" else None

            have = logos.ensure_logos(["td.com", "meta.com", "nowhere.example"], tmp, fetch=fake_fetch)
            self.assertEqual(asked, ["meta.com", "nowhere.example"])  # td.com was already there
            self.assertEqual(have, {"td.com": "td.com.png", "meta.com": "meta.com.jpg"})
            self.assertTrue(os.path.exists(os.path.join(tmp, "meta.com.jpg")))

    def test_missing_domain_file_means_no_icons(self):
        self.assertEqual(logos.load_domains("/nonexistent/company_domains.json"), {})


class EmitTest(unittest.TestCase):
    def test_jobs_json_carries_company_logo_and_dates(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "docs", "logos"))
            with open(os.path.join(tmp, "docs", "logos", "td.com.png"), "wb") as f:
                f.write(PNG)
            with open(os.path.join(tmp, "config.json"), "w") as f:
                json.dump({"keywords": [], "locations": ["toronto"], "sources": [{"type": "workday"}]}, f)
            with open(os.path.join(tmp, "company_domains.json"), "w") as f:
                json.dump({"TD": "td.com"}, f)
            jobs = [Job(uid="workday:td:/job/1", company="TD (Security)", title="Security Analyst I",
                        location="Toronto, Ontario", url="https://td.example/job/1", posted="2026-10-19"),
                    Job(uid="ashby:x:1", company="Unmapped Co", title="SWE", url="https://x.example/1")]
            out = os.path.join(tmp, "docs", "jobs.json")
            cli.emit_jobs_json(out, jobs, os.path.join(tmp, "config.json"),
                               [{"name": "TD", "ok": True, "fetched": 1, "matched": 1}])
            with open(out) as f:
                data = json.load(f)
            td = next(j for j in data["jobs"] if j["company"] == "TD")
            self.assertEqual(td["logo"], "logos/td.com.png")
            self.assertEqual(td["posted"], "2026-10-19")
            other = next(j for j in data["jobs"] if j["company"] == "Unmapped Co")
            self.assertNotIn("logo", other)
            self.assertEqual(data["stats"]["responded"], 1)


if __name__ == "__main__":
    unittest.main()
