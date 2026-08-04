import unittest
from unittest import mock

from jobmonitor import fetchers


class GreenhouseTest(unittest.TestCase):
    @mock.patch("jobmonitor.http.get_json")
    def test_normalizes_fields(self, get_json):
        get_json.return_value = {
            "jobs": [
                {
                    "id": 123,
                    "title": "Software Engineer",
                    "location": {"name": "Toronto, ON"},
                    "absolute_url": "https://example.com/123",
                }
            ]
        }
        jobs = fetchers.fetch_greenhouse({"board": "acme", "name": "Acme"})
        self.assertEqual(len(jobs), 1)
        job = jobs[0]
        self.assertEqual(job.uid, "greenhouse:acme:123")
        self.assertEqual(job.company, "Acme")
        self.assertEqual(job.title, "Software Engineer")
        self.assertEqual(job.location, "Toronto, ON")
        self.assertEqual(job.url, "https://example.com/123")


class AshbyTest(unittest.TestCase):
    @mock.patch("jobmonitor.http.get_json")
    def test_skips_unlisted(self, get_json):
        get_json.return_value = {
            "jobs": [
                {"id": "a", "title": "Listed", "location": "Remote", "jobUrl": "u", "isListed": True},
                {"id": "b", "title": "Hidden", "location": "Remote", "jobUrl": "u", "isListed": False},
            ]
        }
        jobs = fetchers.fetch_ashby({"board": "acme"})
        self.assertEqual([j.title for j in jobs], ["Listed"])


class WorkdayTest(unittest.TestCase):
    @mock.patch("jobmonitor.http.post_json_response")
    def test_paginates_until_empty(self, post):
        post.side_effect = [
            {"jobPostings": [{"title": "Eng I", "externalPath": "/job/1", "locationsText": "Toronto"}]},
            {"jobPostings": []},
        ]
        source = {
            "host": "acme.wd1.myworkdayjobs.com",
            "tenant": "acme",
            "site": "External",
            "pages": 5,
        }
        jobs = fetchers.fetch_workday(source)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].uid, "workday:acme:/job/1")
        self.assertEqual(jobs[0].location, "Toronto")
        self.assertTrue(jobs[0].url.endswith("/en-US/External/job/1"))
        self.assertEqual(post.call_count, 2)  # stopped at the empty page

    @mock.patch("jobmonitor.http.post_json_response")
    def test_country_facet_applied(self, post):
        post.return_value = {"jobPostings": []}
        fetchers.fetch_workday(
            {"host": "h", "tenant": "t", "site": "s", "country": "CAN", "pages": 1}
        )
        sent_payload = post.call_args[0][1]
        self.assertIn("locationCountry", sent_payload["appliedFacets"])


class GoogleTest(unittest.TestCase):
    @mock.patch("jobmonitor.http.get_text")
    def test_scrapes_title_and_id(self, get_text):
        get_text.return_value = (
            '<a href="jobs/results/456-swe-early-career" '
            'aria-label="Learn more about Software Engineer, Early Career">x</a>'
        )
        jobs = fetchers.fetch_google({"query": "swe", "location": "Canada"})
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].uid, "google:456")
        self.assertEqual(jobs[0].title, "Software Engineer, Early Career")
        self.assertEqual(jobs[0].location, "Canada")


class RecruiteeTest(unittest.TestCase):
    @mock.patch("jobmonitor.http.get_json")
    def test_skips_internships(self, get_json):
        get_json.return_value = {
            "offers": [
                {"id": 1, "title": "Engineer", "location": "Waterloo", "careers_url": "u",
                 "employment_type_code": "fulltime"},
                {"id": 2, "title": "Intern", "location": "Waterloo", "careers_url": "u",
                 "employment_type_code": "internship"},
            ]
        }
        jobs = fetchers.fetch_recruitee({"board": "acme"})
        self.assertEqual([j.title for j in jobs], ["Engineer"])


if __name__ == "__main__":
    unittest.main()


class GithubListingsTest(unittest.TestCase):
    @mock.patch("jobmonitor.http.get_json")
    def test_filters_and_dedupes_across_lists(self, get_json):
        import time
        now = int(time.time())
        listing = {
            "id": "aaa",
            "company_name": "Acme",
            "title": "Software Engineer New Grad",
            "locations": ["Toronto, ON, Canada"],
            "url": "https://example.com/j/1?ref=x",
            "active": True,
            "is_visible": True,
            "date_posted": now,
            "sponsorship": "Other",
        }
        get_json.side_effect = [
            [
                listing,
                {**listing, "id": "bbb", "title": "Old", "date_posted": now - 90 * 86400},
                {**listing, "id": "ccc", "title": "Inactive", "active": False},
                {**listing, "id": "ddd", "title": "US only",
                 "url": "https://example.com/j/2",
                 "sponsorship": "U.S. Citizenship is Required"},
            ],
            [{**listing, "id": "eee"}],  # second list repeats the same apply URL
        ]
        jobs = fetchers.fetch_github_listings({"urls": ["u1", "u2"]})
        self.assertEqual(len(jobs), 1)
        job = jobs[0]
        self.assertEqual(job.uid, "ghlist:https://example.com/j/1")
        self.assertEqual(job.company, "Acme")
        self.assertEqual(job.location, "Toronto, ON, Canada")
