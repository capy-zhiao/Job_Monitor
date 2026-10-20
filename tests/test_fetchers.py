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


class PostingDateTest(unittest.TestCase):
    def test_day_reads_each_api_format(self):
        self.assertEqual(fetchers._day("2026-07-24T10:08:28-04:00"), "2026-07-24")
        self.assertEqual(fetchers._day("2026-10-15 17:57:27 UTC"), "2026-10-15")
        self.assertEqual(fetchers._day(1791597276350), "2026-10-10")  # Lever, milliseconds
        self.assertEqual(fetchers._day(1791761082), "2026-10-11")     # Eightfold, seconds
        self.assertEqual(fetchers._day("September  9, 2026"), "2026-09-09")  # Amazon
        self.assertEqual(fetchers._day("Oct 16, 2026"), "2026-10-16")        # Apple
        for unknown in (None, "", "about 1 month", 0, True):
            self.assertEqual(fetchers._day(unknown), "")

    def test_workday_relative_dates(self):
        self.assertEqual(fetchers._workday_posted("Posted Today"), fetchers._days_ago(0))
        self.assertEqual(fetchers._workday_posted("Posted Yesterday"), fetchers._days_ago(1))
        self.assertEqual(fetchers._workday_posted("Posted 5 Days Ago"), fetchers._days_ago(5))
        # "30+" is pushed past a month so it never reads as recent
        self.assertEqual(fetchers._workday_posted("Posted 30+ Days Ago"), fetchers._days_ago(31))
        self.assertEqual(fetchers._workday_posted(None), "")

    @mock.patch("jobmonitor.http.get_json")
    def test_greenhouse_uses_first_published(self, get_json):
        get_json.return_value = {"jobs": [{"id": 1, "title": "SWE", "absolute_url": "u",
                                           "updated_at": "2026-10-01T00:00:00-04:00",
                                           "first_published": "2026-07-24T10:08:28-04:00"}]}
        self.assertEqual(fetchers.fetch_greenhouse({"board": "acme"})[0].posted, "2026-07-24")


class ResolveWorkdayTest(unittest.TestCase):
    JOB = fetchers.Job(uid="workday:td:/job/Toronto/Analyst_R1", company="TD", title="Security Analyst",
                       location="2 Locations", url="https://td.wd3.myworkdayjobs.com/en-US/TD_Bank_Careers/job/Toronto/Analyst_R1",
                       posted="2026-10-01")

    @mock.patch("jobmonitor.http.get_json")
    def test_names_every_location_and_exact_date(self, get_json):
        get_json.return_value = {"jobPostingInfo": {"location": "Toronto, Ontario",
                                                    "additionalLocations": ["Mississauga, Ontario"],
                                                    "startDate": "2026-10-19"}}
        job = fetchers.resolve_workday(self.JOB)
        get_json.assert_called_once_with(
            "https://td.wd3.myworkdayjobs.com/wday/cxs/td/TD_Bank_Careers/job/Toronto/Analyst_R1")
        self.assertEqual(job.location, "Toronto, Ontario; Mississauga, Ontario")
        self.assertEqual(job.posted, "2026-10-19")

    @mock.patch("jobmonitor.http.get_json")
    def test_leaves_named_locations_and_errors_alone(self, get_json):
        named = fetchers.dataclasses.replace(self.JOB, location="Toronto, Ontario")
        self.assertIs(fetchers.resolve_workday(named), named)
        get_json.side_effect = OSError("down")
        self.assertIs(fetchers.resolve_workday(self.JOB), self.JOB)
        self.assertEqual(get_json.call_count, 1)


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
        self.assertEqual(job.posted, fetchers._days_ago(0))
        self.assertFalse(job.sponsors)

    @mock.patch("jobmonitor.http.get_json")
    def test_marks_roles_that_offer_sponsorship(self, get_json):
        import time
        get_json.return_value = [{
            "company_name": "Acme", "title": "Software Engineer New Grad", "locations": ["NYC"],
            "url": "https://example.com/j/9", "active": True, "is_visible": True,
            "date_posted": int(time.time()), "sponsorship": "Offers Sponsorship",
        }]
        self.assertTrue(fetchers.fetch_github_listings({"urls": ["u"]})[0].sponsors)


class MicrosoftTest(unittest.TestCase):
    @mock.patch("jobmonitor.http.get_json")
    def test_normalizes_and_paginates(self, get_json):
        page1 = {"data": {"positions": [
            {"id": 111, "name": "Software Engineer II", "locations": ["Canada, BC, Vancouver"]},
        ]}}
        get_json.return_value = page1
        jobs = fetchers.fetch_microsoft({"query": "software", "location": "Canada", "pages": 2})
        self.assertEqual(len(jobs), 1)
        job = jobs[0]
        self.assertEqual(job.uid, "microsoft:111")
        self.assertEqual(job.title, "Software Engineer II")
        self.assertEqual(job.location, "Canada, BC, Vancouver")
        self.assertTrue(job.url.endswith("/careers/job/111"))
        self.assertEqual(get_json.call_count, 1)


class AppleTest(unittest.TestCase):
    @mock.patch("jobmonitor.http.post_json_response")
    def test_dedupes_on_position_id(self, post):
        post.return_value = {"res": {"searchResults": [
            {"positionId": "2001", "postingTitle": "Software Engineer ",
             "transformedPostingTitle": "software-engineer",
             "team": {"teamCode": "SFTWR"},
             "locations": [{"name": "Vancouver", "countryName": "Canada"}]},
            {"positionId": "2001", "postingTitle": "Software Engineer",
             "transformedPostingTitle": "software-engineer",
             "team": {"teamCode": "SFTWR"},
             "locations": [{"name": "Toronto", "countryName": "Canada"}]},
        ]}}
        jobs = fetchers.fetch_apple({"query": "software engineer", "pages": 1})
        self.assertEqual(len(jobs), 1)
        job = jobs[0]
        self.assertEqual(job.uid, "apple:2001")
        self.assertEqual(job.title, "Software Engineer")
        self.assertEqual(job.location, "Vancouver, Canada")
        self.assertEqual(job.url, "https://jobs.apple.com/en-ca/details/2001/software-engineer?team=SFTWR")


class GoogleTest(unittest.TestCase):
    @mock.patch("jobmonitor.http.post_form")
    def test_parses_batchexecute_envelope(self, post_form):
        import json as j
        inner = j.dumps([[
            ["9001", "Software Developer II", None, None, None, None, None, "Google", None,
             [["Waterloo, ON, Canada", [], "Waterloo", "", "ON", "CA"],
              ["San Jose, CA, USA", [], "San Jose", "", "CA", "US"]]],
        ], None, 1])
        body = ")]}'\n" + j.dumps([["wrb.fr", "r06xKb", inner, None, None, None, "generic"]])
        post_form.return_value = body
        jobs = fetchers.fetch_google({"query": "software", "location": "Canada", "pages": 1})
        self.assertEqual(len(jobs), 1)
        job = jobs[0]
        self.assertEqual(job.uid, "google:9001")
        self.assertEqual(job.title, "Software Developer II")
        self.assertEqual(job.location, "Waterloo, ON, Canada")
        self.assertEqual(job.url, "https://www.google.com/about/careers/applications/jobs/results/9001-software-developer-ii")


class LinkedInParseTest(unittest.TestCase):
    def test_parses_cards_and_skips_malformed_ones(self):
        from jobmonitor import linkedin

        body = (
            '<li><div data-entity-urn="urn:li:jobPosting:111">'
            '<h3 class="base-search-card__title">  Security Engineer &amp; AppSec </h3>'
            '<h4 class="base-search-card__subtitle"><a href="x">Sentry</a></h4>'
            '<span class="job-search-card__location">Toronto, Ontario, Canada</span></div></li>'
            '<li><div data-entity-urn="urn:li:jobPosting:222">no title here</div></li>'
        )
        jobs = linkedin.parse_cards(body)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].uid, "linkedin:111")
        self.assertEqual(jobs[0].title, "Security Engineer & AppSec")
        self.assertEqual(jobs[0].company, "Sentry")
        self.assertEqual(jobs[0].location, "Toronto, Ontario, Canada")
        self.assertEqual(jobs[0].url, "https://www.linkedin.com/jobs/view/111")

    @mock.patch("jobmonitor.http.get_text")
    def test_retries_once_when_rate_limited(self, get_text):
        import urllib.error
        from jobmonitor import linkedin

        limited = urllib.error.HTTPError("u", 429, "Too Many Requests", {}, None)
        card = (
            '<div data-entity-urn="urn:li:jobPosting:1">'
            '<h3 class="base-search-card__title">Security Engineer</h3>'
            '<h4 class="base-search-card__subtitle">Sentry</h4></div>'
        )
        get_text.side_effect = [limited, card]
        jobs, error = linkedin.search([("security", "Canada")], retry_wait=0)
        self.assertIsNone(error)
        self.assertEqual([j.uid for j in jobs], ["linkedin:1"])

        get_text.side_effect = [limited, limited]
        jobs, error = linkedin.search([("security", "Canada")], retry_wait=0)
        self.assertEqual(jobs, [])
        self.assertIn("429", error)


class GithubTablesTest(unittest.TestCase):
    ROW = ('| <a href="https://example.com"><strong>{company}</strong></a> | {title} | {location} | '
           '<a href="{url}"><img src="https://i.imgur.com/x.png" alt="Apply" width="70"/></a> | {age} |')

    def table(self, *rows):
        head = "| Company | Position | Location | Posting | Age |\n|---|---|---|---|---|\n"
        return head + "\n".join(rows)

    @mock.patch("jobmonitor.http.get_text")
    def test_parses_rows_and_skips_old_malformed_and_repeated(self, get_text):
        good = self.ROW.format(company="Acme", title="Software Engineer &amp; Security",
                               location="Toronto, Canada +1",
                               url="https://example.com/jobs?gh_jid=42&amp;x=1#apply", age="3d")
        old = self.ROW.format(company="Acme", title="Old", location="Toronto, Canada",
                              url="https://example.com/jobs/old", age="45d")
        no_age = self.ROW.format(company="Acme", title="No age", location="Toronto, Canada",
                                 url="https://example.com/jobs/noage", age="new")
        repeat = self.ROW.format(company="Acme", title="Same link again", location="Ottawa, Canada",
                                 url="https://example.com/jobs?gh_jid=42&amp;x=1", age="5d")
        four_cells = '| <a href="https://x.com"><strong>Acme</strong></a> | Title | Toronto | 3d |'
        get_text.side_effect = [
            self.table(good, old, no_age, four_cells, "not a table row"),
            self.table(repeat),  # a second file repeating the same apply URL
        ]
        jobs = fetchers.fetch_github_tables({"urls": ["u1", "u2"]})
        self.assertEqual(len(jobs), 1)
        job = jobs[0]
        self.assertEqual(job.uid, "ghtable:https://example.com/jobs?gh_jid=42&x=1")
        self.assertEqual(job.company, "Acme")
        self.assertEqual(job.title, "Software Engineer & Security")
        self.assertEqual(job.location, "Toronto, Canada +1")
        self.assertEqual(job.url, "https://example.com/jobs?gh_jid=42&x=1#apply")
        self.assertEqual(job.posted, fetchers._days_ago(3))  # the "3d" age column

    @mock.patch("jobmonitor.http.get_text")
    def test_max_age_days_is_configurable(self, get_text):
        row = self.ROW.format(company="Acme", title="Dev", location="Toronto, Canada",
                              url="https://example.com/j/1", age="45d")
        get_text.return_value = self.table(row)
        self.assertEqual(fetchers.fetch_github_tables({"urls": ["u"]}), [])
        self.assertEqual(len(fetchers.fetch_github_tables({"urls": ["u"], "max_age_days": 60})), 1)

    @mock.patch("jobmonitor.http.get_text")
    def test_salary_column_and_clearance_roles(self, get_text):
        def six(title, url):
            return ('| <a href="https://example.com"><strong>Acme</strong></a> | %s | Austin, TX | $150k/yr | '
                    '<a href="%s"><img src="x.png"/></a> | 2d |' % (title, url))
        get_text.return_value = "\n".join([
            six("Software Engineer New Grad", "https://example.com/j/1"),
            six("Junior Developer - TS/SCI with Polygraph", "https://example.com/j/2"),
            six("Cloud Analyst - Secret - 4495", "https://example.com/j/3"),
            six("Security Engineer - U.S. Citizenship Required", "https://example.com/j/4"),
            six("Citizen Developer - Jr.", "https://example.com/j/5"),
            six("Secret Management Engineer", "https://example.com/j/6"),
        ])
        jobs = fetchers.fetch_github_tables({"urls": ["u"]})
        self.assertEqual([j.title for j in jobs],
                         ["Software Engineer New Grad", "Citizen Developer - Jr.", "Secret Management Engineer"])
        self.assertEqual(jobs[0].location, "Austin, TX")


class WorkableTest(unittest.TestCase):
    @mock.patch("jobmonitor.http.get_json")
    def test_merges_one_entry_per_location(self, get_json):
        base = {"title": "Developer", "shortcode": "AAA111", "employment_type": "Full-time", "telecommuting": False}
        get_json.return_value = {"name": "Acme", "jobs": [
            {**base, "city": "Toronto", "state": "Ontario", "country": "Canada"},
            {**base, "city": "Montreal", "state": "Quebec", "country": "Canada"},
            {**base, "city": "Toronto", "state": "Ontario", "country": "Canada"},  # repeated place
            {"title": "Remote QA", "shortcode": "BBB222", "telecommuting": True,
             "city": "", "state": "", "country": "Canada"},
            {"title": "No code", "city": "Toronto"},
        ]}
        jobs = fetchers.fetch_workable({"account": "acme", "name": "Acme Inc"})
        self.assertEqual(len(jobs), 2)
        first, second = jobs
        self.assertEqual(first.uid, "workable:acme:AAA111")
        self.assertEqual(first.company, "Acme Inc")
        self.assertEqual(first.location, "Toronto, Ontario, Canada; Montreal, Quebec, Canada")
        self.assertEqual(first.url, "https://apply.workable.com/acme/j/AAA111/")
        self.assertEqual(first.employment_type, "Full-time")
        self.assertEqual(second.location, "Remote; Canada")


class BambooHRTest(unittest.TestCase):
    @mock.patch("jobmonitor.http.get_json")
    def test_builds_location_from_both_objects(self, get_json):
        get_json.return_value = {"result": [
            {"id": "7", "jobOpeningName": "QA Analyst", "employmentStatusLabel": "Full-Time",
             "location": {"city": "Vancouver", "state": "British Columbia"},
             "atsLocation": {"country": None, "state": None, "province": None, "city": None}, "isRemote": None},
            {"id": "8", "jobOpeningName": "Developer", "employmentStatusLabel": None,
             "location": {"city": None, "state": None},
             "atsLocation": {"country": "Canada", "state": "Quebec", "province": None, "city": "Quebec"}, "isRemote": True},
            {"jobOpeningName": "No id"},
        ]}
        jobs = fetchers.fetch_bamboohr({"company": "acme"})
        self.assertEqual(len(jobs), 2)
        self.assertEqual(jobs[0].uid, "bamboohr:acme:7")
        self.assertEqual(jobs[0].location, "Vancouver, British Columbia")
        self.assertEqual(jobs[0].url, "https://acme.bamboohr.com/careers/7")
        self.assertEqual(jobs[0].employment_type, "Full-Time")
        self.assertEqual(jobs[1].location, "Remote, Quebec, Canada")
        self.assertEqual(jobs[1].employment_type, "")


class RipplingTest(unittest.TestCase):
    @mock.patch("jobmonitor.http.get_json")
    def test_pages_and_builds_locations(self, get_json):
        get_json.side_effect = [
            {"page": 0, "totalPages": 2, "items": [
                {"id": "a1", "name": "Software Developer ", "url": "https://ats.rippling.com/acme/jobs/a1",
                 "locations": [{"name": "Toronto, ON", "country": "Canada", "workplaceType": "HYBRID"},
                               {"name": "Canada", "country": "Canada", "workplaceType": "REMOTE"},
                               {"name": "Remote (Canada)", "country": "Canada", "workplaceType": "REMOTE"}]},
                {"name": "No id"},
            ]},
            {"page": 1, "totalPages": 2, "items": [
                {"id": "b2", "name": "QA Analyst", "locations": []},
                # the same job again for another location (Rippling repeats it per place)
                {"id": "a1", "name": "Software Developer ",
                 "locations": [{"name": "Montreal, QC", "country": "Canada", "workplaceType": "ON_SITE"}]},
            ]},
        ]
        jobs = fetchers.fetch_rippling({"board": "acme", "name": "Acme"})
        self.assertEqual(get_json.call_count, 2)
        self.assertEqual([j.uid for j in jobs], ["rippling:acme:a1", "rippling:acme:b2"])
        self.assertEqual(jobs[0].title, "Software Developer")
        self.assertEqual(jobs[0].location, "Toronto, ON, Canada; Remote, Canada; Remote (Canada); Montreal, QC, Canada")
        self.assertEqual(jobs[1].url, "https://ats.rippling.com/acme/jobs/b2")
        self.assertEqual(jobs[1].location, "")


class IcimsPortalTest(unittest.TestCase):
    CARD = ('<li class="iCIMS_JobCardItem"><div class="row"><div class="col-xs-6 header left">'
            '<span class="sr-only field-label">Location</span> <span > {loc}</span></div>'
            '<div class="col-xs-12 title"><a href="https://careers-acme.icims.com/jobs/{id}/{slug}/job?in_iframe=1" '
            'class="iCIMS_Anchor" title="{id} - {title}"><h3>{title}</h3></a></div></div></li>')

    @mock.patch("jobmonitor.http.get_text")
    def test_reads_pages_until_nothing_new(self, get_text):
        page0 = "<ul>" + self.CARD.format(loc="CA-ON-Ottawa", id="11", slug="dev", title="Associate Software Developer") \
            + self.CARD.format(loc="US-TX-Austin", id="12", slug="qa", title="QA &amp; Test") + "</ul>"
        page1 = "<ul>" + self.CARD.format(loc="CA-ON-Ottawa", id="11", slug="dev", title="Associate Software Developer") + "</ul>"
        get_text.side_effect = [page0, page1]
        jobs = fetchers.fetch_icims_portal({"host": "careers-acme.icims.com", "name": "Acme"})
        self.assertEqual(get_text.call_count, 2)
        self.assertEqual([j.uid for j in jobs], ["icimsportal:careers-acme.icims.com:11", "icimsportal:careers-acme.icims.com:12"])
        self.assertEqual(jobs[0].location, "CA-ON-Ottawa, Canada")
        self.assertEqual(jobs[0].url, "https://careers-acme.icims.com/jobs/11/dev/job")
        self.assertEqual(jobs[1].title, "QA & Test")
        self.assertEqual(jobs[1].location, "US-TX-Austin")


class JobviteTest(unittest.TestCase):
    @mock.patch("jobmonitor.http.get_text")
    def test_parses_job_rows(self, get_text):
        get_text.return_value = (
            '<tr><td class="jv-job-list-name"> <a href="/acme/job/oAB1">IT Support Analyst</a> </td>'
            '<td class="jv-job-list-location"> Vancouver, British Columbia </td></tr>'
            '<tr><td class="jv-job-list-name"> <a href="/acme/job/oAB2">Developer &amp; QA</a> </td>'
            '<td class="jv-job-list-location"> Remote,\n Canada </td></tr>'
        )
        jobs = fetchers.fetch_jobvite({"company": "acme", "name": "Acme"})
        self.assertEqual([j.uid for j in jobs], ["jobvite:acme:oAB1", "jobvite:acme:oAB2"])
        self.assertEqual(jobs[0].url, "https://jobs.jobvite.com/acme/job/oAB1")
        self.assertEqual(jobs[1].title, "Developer & QA")
        self.assertEqual(jobs[1].location, "Remote, Canada")

