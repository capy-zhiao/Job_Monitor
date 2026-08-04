"""Per-platform fetchers.

Each fetcher takes a `source` config dict and returns a ``list[Job]``. New
platforms are added by writing a function and registering it in ``FETCHERS``.
"""

import re
import time
import urllib.parse

from . import http
from .models import Job


def fetch_greenhouse(source):
    """Greenhouse public board API. Companies: Stripe, Datadog, Coinbase, ...

    source: board
    """
    board = source["board"]
    data = http.get_json(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs")
    return [
        Job(
            uid=f"greenhouse:{board}:{j['id']}",
            company=source.get("name", board),
            title=j.get("title", ""),
            location=(j.get("location") or {}).get("name", ""),
            url=j.get("absolute_url", ""),
        )
        for j in data.get("jobs", [])
    ]


def fetch_lever(source):
    """Lever public postings API. Companies: Palantir, Waabi, Magnet Forensics, ...

    source: company
    """
    company = source["company"]
    data = http.get_json(f"https://api.lever.co/v0/postings/{company}?mode=json")
    return [
        Job(
            uid=f"lever:{company}:{j['id']}",
            company=source.get("name", company),
            title=j.get("text", ""),
            location=(j.get("categories") or {}).get("location", ""),
            url=j.get("hostedUrl", ""),
        )
        for j in data
    ]


def fetch_ashby(source):
    """Ashby public job-board API. Companies: OpenAI, Cohere, 1Password, Vanta, ...

    source: board
    """
    board = source["board"]
    data = http.get_json(f"https://api.ashbyhq.com/posting-api/job-board/{board}")
    jobs = []
    for j in data.get("jobs", []):
        if j.get("isListed") is False:
            continue
        jobs.append(
            Job(
                uid=f"ashby:{board}:{j['id']}",
                company=source.get("name", board),
                title=j.get("title", ""),
                location=j.get("location", ""),
                url=j.get("jobUrl", ""),
                employment_type=j.get("employmentType", ""),
            )
        )
    return jobs


def fetch_amazon(source):
    """Amazon jobs search JSON endpoint.

    source: query, countries (list of ISO-3 codes), limit
    """
    params = {
        "base_query": source.get("query", "software development engineer"),
        "sort": "recent",
        "result_limit": str(source.get("limit", 100)),
        "offset": "0",
    }
    qs = urllib.parse.urlencode(params)
    for country in source.get("countries", []):
        qs += "&" + urllib.parse.urlencode({"normalized_country_code[]": country})
    data = http.get_json(f"https://www.amazon.jobs/en/search.json?{qs}")
    return [
        Job(
            uid=f"amazon:{j['id_icims']}",
            company=source.get("name", "Amazon"),
            title=j.get("title", ""),
            location=j.get("location", ""),
            url="https://www.amazon.jobs" + j.get("job_path", ""),
        )
        for j in data.get("jobs", [])
    ]


# Workday "locationCountry" facet GUIDs are shared across many tenants, but some
# tenants ignore this facet entirely, so always pair it with a client-side
# location filter rather than relying on it alone.
WORKDAY_COUNTRY_FACETS = {
    "CAN": "a30a87ed25634629aa6c3958aa2b91ea",
    "USA": "bc33aa3152ec42d4995f4791a106ed09",
}


def fetch_workday(source):
    """Workday CXS jobs API. Companies: TD, CrowdStrike, Trend Micro, Arctic Wolf, ...

    source: host, tenant, site, search, country (optional), pages (optional)
    """
    host, tenant, site = source["host"], source["tenant"], source["site"]
    url = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
    facets = {}
    if source.get("country") in WORKDAY_COUNTRY_FACETS:
        facets["locationCountry"] = [WORKDAY_COUNTRY_FACETS[source["country"]]]
    jobs = []
    for page in range(source.get("pages", 3)):
        data = http.post_json_response(
            url,
            {
                "appliedFacets": facets,
                "limit": 20,
                "offset": page * 20,
                "searchText": source.get("search", "software engineer"),
            },
        )
        postings = data.get("jobPostings", [])
        if not postings:
            break
        for j in postings:
            path = j.get("externalPath", "")
            jobs.append(
                Job(
                    uid=f"workday:{tenant}:{path}",
                    company=source.get("name", tenant),
                    title=j.get("title", ""),
                    location=j.get("locationsText", ""),
                    url=f"https://{host}/en-US/{site}{path}",
                )
            )
    return jobs


def fetch_phenom(source):
    """Phenom People search widget API. Companies: RBC, ...

    source: host, search, country (optional), size (optional)
    """
    host = source["host"]
    payload = {
        "lang": "en_ca",
        "deviceType": "desktop",
        "country": "ca",
        "pageName": "search-results",
        "ddoKey": "refineSearch",
        "sortBy": "Most recent",
        "from": 0,
        "jobs": True,
        "counts": True,
        "all_fields": ["category", "location"],
        "size": source.get("size", 50),
        "keywords": source.get("search", "software engineer"),
        "global": True,
        "selected_fields": {},
        "siteType": "external",
    }
    if source.get("country"):
        payload["selected_fields"] = {"country": [source["country"]]}
    data = http.post_json_response(f"https://{host}/widgets", payload)
    jobs = []
    for j in data.get("refineSearch", {}).get("data", {}).get("jobs", []):
        apply_url = (j.get("applyUrl") or "").removesuffix("/apply")
        jobs.append(
            Job(
                uid=f"phenom:{host}:{j.get('jobId')}",
                company=source.get("name", host),
                title=j.get("title", ""),
                location=j.get("location", "") or j.get("cityState", ""),
                url=apply_url or f"https://{host}/ca/en/job/{j.get('jobSeqNo')}",
            )
        )
    return jobs


def fetch_eightfold(source):
    """Eightfold.ai jobs API. Companies: Netflix, ...

    source: host, domain, query, location (optional), num (optional)
    """
    params = {
        "domain": source["domain"],
        "query": source.get("query", "software engineer"),
        "num": str(source.get("num", 50)),
        "start": "0",
    }
    if source.get("location"):
        params["location"] = source["location"]
    url = f"https://{source['host']}/api/apply/v2/jobs?" + urllib.parse.urlencode(params)
    data = http.get_json(url)
    return [
        Job(
            uid=f"eightfold:{source['host']}:{p['id']}",
            company=source.get("name", source["domain"]),
            title=p.get("name", ""),
            location=p.get("location", ""),
            url=p.get("canonicalPositionUrl", ""),
        )
        for p in data.get("positions", [])
    ]


def fetch_recruitee(source):
    """Recruitee public offers API. Companies: Huawei Canada, ...

    source: board (subdomain)
    """
    board = source["board"]
    data = http.get_json(f"https://{board}.recruitee.com/api/offers/")
    jobs = []
    for j in data.get("offers", []):
        if j.get("employment_type_code") == "internship":
            continue
        jobs.append(
            Job(
                uid=f"recruitee:{board}:{j['id']}",
                company=source.get("name", board),
                title=j.get("title", ""),
                location=j.get("location", ""),
                url=j.get("careers_url", ""),
            )
        )
    return jobs


def fetch_google(source):
    """Google Careers results page (HTML scrape; no public API).

    source: query, location (optional), target_level (optional, e.g. "EARLY")
    """
    params = {"q": source.get("query", "software engineer")}
    if source.get("location"):
        params["location"] = source["location"]
    if source.get("target_level"):
        params["target_level"] = source["target_level"]
    url = (
        "https://www.google.com/about/careers/applications/jobs/results?"
        + urllib.parse.urlencode(params)
    )
    html = http.get_text(url)
    jobs, seen_ids = [], set()
    for match in re.finditer(r"<a[^>]*>", html):
        tag = match.group(0)
        href = re.search(r'href="(jobs/results/(\d+)[^"?]*)', tag)
        label = re.search(r'aria-label="Learn more about ([^"]+)"', tag)
        if not href or not label:
            continue
        job_id = href.group(2)
        if job_id in seen_ids:
            continue
        seen_ids.add(job_id)
        jobs.append(
            Job(
                uid=f"google:{job_id}",
                company=source.get("name", "Google"),
                title=label.group(1),
                location=source.get("location", ""),
                url="https://www.google.com/about/careers/applications/" + href.group(1),
            )
        )
    return jobs


def fetch_shopify(source):
    """Shopify Careers page (HTML scrape; no public API).

    source: query, pages (optional)
    """
    jobs, seen_hrefs = [], set()
    for page in range(1, source.get("pages", 2) + 1):
        qs = urllib.parse.urlencode({"query": source.get("query", "engineer"), "page": page})
        html = http.get_text(f"https://www.shopify.com/careers?{qs}")
        found = 0
        for href, inner in re.findall(
            r'<a[^>]*href="(/careers/[a-z0-9-]+_[a-f0-9-]{36})"[^>]*>(.*?)</a>',
            html,
            re.S,
        ):
            if href in seen_hrefs:
                continue
            seen_hrefs.add(href)
            found += 1
            parts = [p.strip() for p in re.sub(r"<[^>]+>", "|", inner).split("|") if p.strip()]
            jobs.append(
                Job(
                    uid=f"shopify:{href}",
                    company=source.get("name", "Shopify"),
                    title=parts[0] if parts else "",
                    location=parts[1] if len(parts) > 1 else "",
                    url="https://www.shopify.com" + href,
                )
            )
        if not found:
            break
    return jobs


def fetch_github_listings(source):
    """Community-maintained GitHub new-grad list repos (Simplify-lineage
    listings.json, e.g. SimplifyJobs/New-Grad-Positions, vanshb03/New-Grad-2027).

    source: urls (list of raw listings.json URLs), max_age_days (optional, default 30)

    Listings marked citizenship-required are dropped at the source. The uid is
    keyed on the normalized apply URL so the same posting appearing in several
    list repos alerts only once.
    """
    cutoff = time.time() - source.get("max_age_days", 30) * 86400
    jobs, seen_urls = [], set()
    for url in source["urls"]:
        for j in http.get_json(url):
            if not j.get("active") or not j.get("is_visible"):
                continue
            if j.get("sponsorship") == "U.S. Citizenship is Required":
                continue
            posted = j.get("date_posted") or j.get("date_updated") or 0
            if posted < cutoff:
                continue
            apply_url = j.get("url", "")
            key = apply_url.split("?")[0].split("#")[0].rstrip("/")
            if not key or key in seen_urls:
                continue
            seen_urls.add(key)
            jobs.append(
                Job(
                    uid=f"ghlist:{key}",
                    company=j.get("company_name", ""),
                    title=j.get("title", ""),
                    location="; ".join(j.get("locations") or []),
                    url=apply_url,
                )
            )
    return jobs


FETCHERS = {
    "github_listings": fetch_github_listings,
    "greenhouse": fetch_greenhouse,
    "lever": fetch_lever,
    "ashby": fetch_ashby,
    "amazon": fetch_amazon,
    "workday": fetch_workday,
    "phenom": fetch_phenom,
    "eightfold": fetch_eightfold,
    "recruitee": fetch_recruitee,
    "google": fetch_google,
    "shopify": fetch_shopify,
}
