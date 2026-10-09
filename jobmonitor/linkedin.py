"""LinkedIn public job search (the logged-out "jobs-guest" endpoint).

Used only by the on-demand /linkedin Discord bot, never by the scheduled monitor:
LinkedIn blocks datacenter IPs and its terms forbid automated scraping, so this
runs only when asked, at low volume, from a home connection.
"""

import html
import re
import time
import urllib.error
import urllib.parse

from . import http
from .models import Job

SEARCH_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
PAGE_SIZE = 10


def _clean(fragment):
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", fragment))).strip()


def parse_cards(body):
    """Parse a search response: a flat list of job cards. Each card is split out
    and parsed on its own so one malformed card cannot break the rest."""
    jobs = []
    for chunk in body.split('data-entity-urn="urn:li:jobPosting:')[1:]:
        job_id = re.match(r"(\d+)", chunk)
        title = re.search(r'class="base-search-card__title"[^>]*>([\s\S]*?)</h3>', chunk)
        if not job_id or not title:
            continue
        company = re.search(r'class="base-search-card__subtitle"[^>]*>([\s\S]*?)</h4>', chunk)
        location = re.search(r'class="job-search-card__location"[^>]*>([\s\S]*?)</span>', chunk)
        jobs.append(
            Job(
                uid="linkedin:" + job_id.group(1),
                company=_clean(company.group(1)) if company else "",
                title=_clean(title.group(1)),
                location=_clean(location.group(1)) if location else "",
                url="https://www.linkedin.com/jobs/view/" + job_id.group(1),
            )
        )
    return jobs


def search(queries, days=7, pages=1, delay=3.0):
    """Run (keywords, location) searches and return (jobs, error).

    Jobs are de-duplicated across queries. If LinkedIn starts refusing requests,
    the searches stop early and the partial results come back with the error.
    """
    jobs, seen = [], set()
    first = True
    for keywords, location in queries:
        for page in range(pages):
            if not first:
                time.sleep(delay)
            first = False
            params = {
                "keywords": keywords,
                "location": location,
                "f_TPR": "r%d" % (days * 86400),
                "start": str(page * PAGE_SIZE),
            }
            try:
                body = http.get_text(SEARCH_URL + "?" + urllib.parse.urlencode(params))
            except urllib.error.HTTPError as exc:
                return jobs, "LinkedIn refused the request (HTTP %d)" % exc.code
            except urllib.error.URLError as exc:
                return jobs, "network error: %s" % exc.reason
            page_jobs = parse_cards(body)
            for job in page_jobs:
                if job.uid not in seen:
                    seen.add(job.uid)
                    jobs.append(job)
            if len(page_jobs) < PAGE_SIZE:
                break
    return jobs, None
