"""Per-platform fetchers.

Each fetcher takes a `source` config dict and returns a ``list[Job]``. New
platforms are added by writing a function and registering it in ``FETCHERS``.
"""

import dataclasses
import html
import re
import time
import urllib.parse
from datetime import datetime, timedelta, timezone

from . import http
from .models import Job


def _day(value):
    """A posting date as ``YYYY-MM-DD`` from what the APIs return: an ISO
    timestamp, epoch seconds or milliseconds, or text like "September 9, 2026".
    Anything else gives "", meaning the date is unknown."""
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
        if value > 1e11:  # milliseconds
            value /= 1000
        return datetime.fromtimestamp(value, timezone.utc).date().isoformat()
    if isinstance(value, str):
        text = " ".join(value.split())
        if re.match(r"\d{4}-\d{2}-\d{2}", text):
            return text[:10]
        for fmt in ("%B %d, %Y", "%b %d, %Y"):
            try:
                return datetime.strptime(text, fmt).date().isoformat()
            except ValueError:
                pass
    return ""


def _days_ago(days):
    return (datetime.now(timezone.utc).date() - timedelta(days=days)).isoformat()


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
            posted=_day(j.get("first_published")),
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
            posted=_day(j.get("createdAt")),
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
                posted=_day(j.get("publishedAt")),
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
            posted=_day(j.get("posted_date")),
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

    source: host, tenant, site, search, country (optional), pages (optional),
    facets (optional dict of raw appliedFacets for tenants with custom facet
    GUIDs, e.g. NVIDIA's locationHierarchy1)
    """
    host, tenant, site = source["host"], source["tenant"], source["site"]
    url = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
    facets = dict(source.get("facets", {}))
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
                    posted=_workday_posted(j.get("postedOn")),
                )
            )
    return jobs


def _workday_posted(text):
    """Workday lists say only "Posted Today", "Posted 3 Days Ago" or "Posted 30+
    Days Ago". "30+" becomes 31 days, so the role reads as over a month old."""
    text = (text or "").lower()
    if "today" in text:
        return _days_ago(0)
    if "yesterday" in text:
        return _days_ago(1)
    m = re.search(r"(\d+)(\+?)\s*days?\s+ago", text)
    return _days_ago(int(m.group(1)) + (1 if m.group(2) else 0)) if m else ""


def resolve_workday(job):
    """Name the places of a Workday posting listed as "2 Locations".

    The list endpoint gives only the count, so such a posting showed up as
    "2 Locations" and failed every location filter. The job's detail endpoint
    names the main location and the additional ones, and gives the exact posting
    date. Only postings whose title already matched are resolved, which keeps
    this to a few requests per run; on any error the job is returned unchanged.
    """
    if not re.fullmatch(r"\d+ Locations?", job.location or ""):
        return job
    parts = urllib.parse.urlsplit(job.url)
    m = re.match(r"/en-US/([^/]+)(/.+)", parts.path)
    if not m:
        return job
    site, path = m.groups()
    tenant = job.uid.split(":", 2)[1]
    try:
        info = http.get_json(f"https://{parts.netloc}/wday/cxs/{tenant}/{site}{path}").get("jobPostingInfo") or {}
    except Exception:
        return job
    places = [p for p in [info.get("location"), *(info.get("additionalLocations") or [])] if p]
    if not places:
        return job
    return dataclasses.replace(job, location="; ".join(places), posted=_day(info.get("startDate")) or job.posted)


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
                posted=_day(j.get("postedDate")),
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
                posted=_day(j.get("published_at")),
            )
        )
    return jobs


def fetch_google(source):
    """Google Careers batchexecute RPC (the XHR behind the results page).

    source: query, location (optional, e.g. "Canada"), pages (optional)

    The results page is a JS app; job data comes from the r06xKb RPC. The
    request is double-encoded (f.req is JSON whose inner element is itself a
    JSON string) and the response starts with an anti-JSON )]}' prefix.
    The old target_level=EARLY server-side facet is defunct — entry-level
    filtering happens client-side on titles like every other source.
    """
    import json as _json

    url = (
        "https://www.google.com/about/careers/applications/_/HiringCportalFrontendUi"
        "/data/batchexecute?rpcids=r06xKb&source-path=%2Fabout%2Fcareers%2Fapplications"
        "%2Fjobs%2Fresults&hl=en-US"
    )
    location = source.get("location")
    jobs = []
    for page in range(1, source.get("pages", 2) + 1):
        inner = [[
            source.get("query", "software engineer"),
            None, None, None, "en-US", None,
            [[location]] if location else None,
            page,
        ]]
        freq = _json.dumps([[["r06xKb", _json.dumps(inner), None, "generic"]]])
        text = http.post_form(url, {"f.req": freq})
        if text.startswith(")]}'"):
            text = text[4:]
        payload, _ = _json.JSONDecoder().raw_decode(text.lstrip())
        row = next(
            (r for r in payload if isinstance(r, list) and r and r[0] == "wrb.fr" and r[1] == "r06xKb"),
            None,
        )
        if row is None or not row[2]:
            break
        result = _json.loads(row[2])
        postings = result[0] or []
        if not postings:
            break
        for j in postings:
            job_id = str(j[0])
            title = j[1] or ""
            locs = j[9] or []
            canadian = [l[0] for l in locs if len(l) > 5 and l[5] == "CA"]
            display = canadian or [l[0] for l in locs if l]
            slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
            jobs.append(
                Job(
                    uid=f"google:{job_id}",
                    company=source.get("name", "Google"),
                    title=title,
                    location="; ".join(display),
                    url=f"https://www.google.com/about/careers/applications/jobs/results/{job_id}-{slug}",
                )
            )
        if len(postings) < 20:
            break
    return jobs


def fetch_microsoft(source):
    """Microsoft careers via the Eightfold PCSX search API.

    source: query, location (optional, e.g. "Canada"), pages (optional)

    The pre-2026 gcsservices.careers.microsoft.com endpoint is dead (stale
    azureedge.net TLS cert). Page size is fixed at 10 (num below 10 is ignored).
    """
    jobs = []
    for page in range(source.get("pages", 2)):
        params = {
            "domain": "microsoft.com",
            "query": source.get("query", "software engineer"),
            "start": str(page * 10),
            "num": "10",
            "sort_by": "relevance",
        }
        if source.get("location"):
            params["location"] = source["location"]
        url = "https://apply.careers.microsoft.com/api/pcsx/search?" + urllib.parse.urlencode(params)
        data = http.get_json(url)
        positions = (data.get("data") or {}).get("positions") or []
        if not positions:
            break
        for j in positions:
            job_id = str(j.get("id", ""))
            jobs.append(
                Job(
                    uid=f"microsoft:{job_id}",
                    company=source.get("name", "Microsoft"),
                    title=j.get("name", ""),
                    location="; ".join(j.get("locations") or []),
                    url=f"https://apply.careers.microsoft.com/careers/job/{job_id}",
                    posted=_day(j.get("postedTs")),
                )
            )
        if len(positions) < 10:
            break
    return jobs


def fetch_apple(source):
    """Apple jobs search API at jobs.apple.com.

    source: query, location (optional postLocation id, default Canada), pages (optional)

    The body must carry "sort" and "format" exactly as the site's client sends
    them — omitting either returns HTTP 200 with zero results rather than an
    error. Multi-location postings repeat per location with the same
    positionId, so dedupe on positionId.
    """
    jobs, seen_positions = [], set()
    for page in range(1, source.get("pages", 2) + 1):
        payload = {
            "query": source.get("query", "software engineer"),
            "filters": {"locations": [source.get("location", "postLocation-CANC")]},
            "page": page,
            "locale": "en-ca",
            "sort": "newest",
            "format": {"longDate": "MMMM D, YYYY", "mediumDate": "MMM D, YYYY"},
        }
        data = http.post_json_response("https://jobs.apple.com/api/v1/search", payload)
        results = (data.get("res") or {}).get("searchResults") or []
        if not results:
            break
        for j in results:
            position_id = str(j.get("positionId", ""))
            if not position_id or position_id in seen_positions:
                continue
            seen_positions.add(position_id)
            loc = (j.get("locations") or [{}])[0]
            location = ", ".join(x for x in [loc.get("name"), loc.get("countryName")] if x)
            slug = j.get("transformedPostingTitle", "")
            team = (j.get("team") or {}).get("teamCode", "")
            url = f"https://jobs.apple.com/en-ca/details/{position_id}/{slug}"
            if team:
                url += f"?team={team}"
            jobs.append(
                Job(
                    uid=f"apple:{position_id}",
                    company=source.get("name", "Apple"),
                    title=(j.get("postingTitle") or "").strip(),
                    location=location,
                    url=url,
                    posted=_day(j.get("postDateInGMT") or j.get("postingDate")),
                )
            )
        if len(results) < 20:
            break
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

    source: urls (list of raw listings.json URLs), max_age_days (optional, default 30),
    skip_no_sponsorship_outside_canada (optional bool)

    Listings marked citizenship-required are dropped at the source. The uid is
    keyed on the normalized apply URL so the same posting appearing in several
    list repos alerts only once. With skip_no_sponsorship_outside_canada, roles
    flagged "Does Not Offer Sponsorship" are also dropped unless they include a
    Canadian location — Canadian roles are workable on a PGWP without sponsorship.
    Roles flagged "Offers Sponsorship" are marked with ``sponsors``.
    """
    cutoff = time.time() - source.get("max_age_days", 30) * 86400
    jobs, seen_urls = [], set()
    for url in source["urls"]:
        for j in http.get_json(url):
            if not j.get("active") or not j.get("is_visible"):
                continue
            if j.get("sponsorship") == "U.S. Citizenship is Required":
                continue
            if (source.get("skip_no_sponsorship_outside_canada")
                    and j.get("sponsorship") == "Does Not Offer Sponsorship"
                    and not any("canada" in loc.lower() for loc in (j.get("locations") or []))):
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
                    posted=_day(j.get("date_posted")),
                    sponsors=j.get("sponsorship") == "Offers Sponsorship",
                )
            )
    return jobs


def fetch_github_tables(source):
    """Community GitHub job lists that publish only a markdown table, no JSON
    (speedyapply/2027-SWE-College-Jobs: NEW_GRAD_INTL.md, INTERN_INTL.md).

    source: urls (raw .md files), max_age_days (optional, default 30)

    Rows look like ``| Company | Position | Location | Posting | Age |`` with HTML
    inside the cells and the age written as ``11d``; some sections add a Salary
    column before Posting. Rows that do not parse (other cell counts, no apply
    link, no age) are skipped rather than failing the list, and so are roles that
    require a security clearance or U.S. citizenship.
    The uid is the apply URL minus its fragment, so a repeat within or across
    files alerts once; the query string stays because some boards carry the job
    id there (``?gh_jid=...``).
    """
    max_age = source.get("max_age_days", 30)
    jobs, seen_urls = [], set()
    for url in source["urls"]:
        for line in http.get_text(url).splitlines():
            if not line.startswith("| <a"):
                continue
            cells = re.split(r"\s\|\s", line.strip().strip("|").strip())
            if len(cells) == 6:  # a Salary column sits between Location and Posting
                del cells[3]
            if len(cells) != 5:
                continue
            company, title, location, posting, age = cells
            href = re.search(r'href="([^"]+)"', posting)
            days = re.fullmatch(r"(\d+)d", age.strip())
            if not href or not days or int(days.group(1)) > max_age:
                continue
            if _NEEDS_CLEARANCE.search(_cell_text(title)):
                continue
            apply_url = html.unescape(href.group(1))
            key = apply_url.split("#")[0].rstrip("/")
            if key in seen_urls:
                continue
            seen_urls.add(key)
            jobs.append(
                Job(
                    uid=f"ghtable:{key}",
                    company=_cell_text(company),
                    title=_cell_text(title),
                    location=_cell_text(location),
                    url=apply_url,
                    posted=_days_ago(int(days.group(1))),
                )
            )
    return jobs


# Clearance and citizenship requirements in a position title. "Citizen Developer"
# (a low-code role) is not one, so only "citizenship" is matched.
_NEEDS_CLEARANCE = re.compile(
    r"clearance|ts/sci|citizenship|polygraph|\bsecret\s*(?:-|required|or\b|$)", re.I)


def _cell_text(cell):
    return html.unescape(re.sub(r"<[^>]+>", "", cell)).strip()


def fetch_workable(source):
    """Workable job boards (apply.workable.com/<account>), public widget feed.

    source: account (the slug in the board URL)

    The feed lists every published job in one response, one entry per location, so
    entries are merged on the shortcode and their places joined with "; ". Remote
    jobs get "Remote" added to the location.
    """
    account = source["account"]
    data = http.get_json(f"https://apply.workable.com/api/v1/widget/accounts/{account}")
    merged = {}
    for j in data.get("jobs") or []:
        code = j.get("shortcode")
        if not code:
            continue
        entry = merged.setdefault(code, {"job": j, "places": []})
        place = ", ".join(p for p in (j.get("city"), j.get("state"), j.get("country")) if p)
        if place and place not in entry["places"]:
            entry["places"].append(place)
    jobs = []
    for code, entry in merged.items():
        j = entry["job"]
        places = entry["places"]
        if j.get("telecommuting"):
            places = ["Remote"] + places
        jobs.append(
            Job(
                uid=f"workable:{account}:{code}",
                company=source.get("name", account),
                title=j.get("title", ""),
                location="; ".join(places),
                url=f"https://apply.workable.com/{account}/j/{code}/",
                employment_type=j.get("employment_type", ""),
                posted=_day(j.get("published_on")),
            )
        )
    return jobs


def fetch_bamboohr(source):
    """BambooHR career pages (<company>.bamboohr.com/careers), public JSON list.

    source: company (the subdomain)

    The location comes from two objects that are filled in differently from one
    company to the next, so city, state and country are taken from both.
    """
    company = source["company"]
    data = http.get_json(f"https://{company}.bamboohr.com/careers/list")
    jobs = []
    for j in data.get("result") or []:
        if j.get("id") is None:
            continue
        parts = []
        for place in (j.get("location") or {}, j.get("atsLocation") or {}):
            for key in ("city", "state", "province", "country"):
                value = place.get(key)
                if value and value not in parts:
                    parts.append(value)
        if j.get("isRemote"):
            parts.insert(0, "Remote")
        jobs.append(
            Job(
                uid=f"bamboohr:{company}:{j['id']}",
                company=source.get("name", company),
                title=j.get("jobOpeningName", ""),
                location=", ".join(parts),
                url=f"https://{company}.bamboohr.com/careers/{j['id']}",
                employment_type=j.get("employmentStatusLabel") or "",
            )
        )
    return jobs


def fetch_rippling(source):
    """Rippling Recruiting boards (ats.rippling.com/<board>/jobs), public board API.

    source: board (the slug in the board URL)

    The v2 endpoint pages its results and reports totalPages. A job posted in
    several places comes back once per location under the same id, so entries
    are merged on the id and their places joined with "; ". Remote locations
    carry workplaceType REMOTE and get "Remote" added unless the name says it.
    """
    board = source["board"]
    merged, page = {}, 0
    while page < 50:
        data = http.get_json(
            f"https://ats.rippling.com/api/v2/board/{board}/jobs?page={page}&pageSize=100"
        )
        items = data.get("items") or []
        for j in items:
            if not j.get("id"):
                continue
            entry = merged.setdefault(j["id"], {"job": j, "places": []})
            for loc in j.get("locations") or []:
                name = (loc.get("name") or "").strip()
                country = loc.get("country") or ""
                place = name if not country or country.lower() in name.lower() else ", ".join(p for p in (name, country) if p)
                if loc.get("workplaceType") == "REMOTE" and "remote" not in place.lower():
                    place = "Remote, " + place if place else "Remote"
                if place and place not in entry["places"]:
                    entry["places"].append(place)
        page += 1
        if not items or page >= (data.get("totalPages") or 1):
            break
    return [
        Job(
            uid=f"rippling:{board}:{job_id}",
            company=source.get("name", board),
            title=(entry["job"].get("name") or "").strip(),
            location="; ".join(entry["places"]),
            url=entry["job"].get("url") or f"https://ats.rippling.com/{board}/jobs/{job_id}",
        )
        for job_id, entry in merged.items()
    ]


def fetch_icims_portal(source):
    """Classic iCIMS career portals (careers-<company>.icims.com), HTML search pages.
    Companies: Kinaxis, ...

    source: host (e.g. careers-kinaxis.icims.com)

    These older portals have no JSON API (the icims fetcher's /api/jobs returns
    HTML here), so the search results are read page by page (pr=0, 1, ...). Each
    job card carries the location as "CA-ON-Ottawa"; ", Canada" is added to
    Canadian ones so the location filter recognises them.
    """
    host = source["host"]
    jobs, seen_ids = [], set()
    for page in range(30):
        body = http.get_text(f"https://{host}/jobs/search?pr={page}&searchRelation=keyword_all&in_iframe=1")
        cards = body.split('<li class="iCIMS_JobCardItem">')[1:]
        new = 0
        for card in cards:
            link = re.search(r'href="(https://[^"]+/jobs/(\d+)/[^"?]+/job)[^"]*"[^>]*title="\d+ - ([^"]*)"', card)
            if not link or link.group(2) in seen_ids:
                continue
            seen_ids.add(link.group(2))
            new += 1
            places = re.findall(r'field-label">(?:Additional )?Locations?</span>\s*(?:</dt>\s*<dd[^>]*>)?\s*<span[^>]*>(.*?)</span>', card, re.S)
            places = [_cell_text(p) for p in places if _cell_text(p)]
            places = [p + ", Canada" if p.startswith("CA-") else p for p in places]
            places = list(dict.fromkeys(places))  # the main and additional location can repeat
            jobs.append(
                Job(
                    uid=f"icimsportal:{host}:{link.group(2)}",
                    company=source.get("name", host),
                    title=html.unescape(link.group(3)).strip(),
                    location="; ".join(places),
                    url=link.group(1),
                )
            )
        if not cards or not new:
            break
    return jobs


def fetch_jobvite(source):
    """Jobvite career pages (jobs.jobvite.com/<company>/jobs), HTML job list.
    Companies: Absolute Security, ...

    source: company (the slug in the page URL)
    """
    company = source["company"]
    body = http.get_text(f"https://jobs.jobvite.com/{company}/jobs")
    rows = re.findall(
        r'<td class="jv-job-list-name">\s*<a href="(/[^"]+/job/([^"/]+))">(.*?)</a>\s*</td>\s*'
        r'<td class="jv-job-list-location">(.*?)</td>',
        body, re.S,
    )
    jobs, seen_ids = [], set()
    for path, job_id, title, location in rows:
        if job_id in seen_ids:
            continue
        seen_ids.add(job_id)
        jobs.append(
            Job(
                uid=f"jobvite:{company}:{job_id}",
                company=source.get("name", company),
                title=_cell_text(title),
                location=re.sub(r"\s+", " ", _cell_text(location)),
                url="https://jobs.jobvite.com" + path,
            )
        )
    return jobs


FETCHERS = {
    "github_listings": fetch_github_listings,
    "github_tables": fetch_github_tables,
    "workable": fetch_workable,
    "bamboohr": fetch_bamboohr,
    "rippling": fetch_rippling,
    "icims_portal": fetch_icims_portal,
    "jobvite": fetch_jobvite,
    "microsoft": fetch_microsoft,
    "apple": fetch_apple,
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


# --- Fetchers ported from the AFM monitor (shared lineage) ---

def fetch_successfactors(source):
    """SAP SuccessFactors career sites (jobs2web) public RSS feed.
    Companies: Scotiabank, Deloitte Canada, EY, ...

    source: host, search, location_search (optional, e.g. "Canada" or
    '"United States"'). Feed caps at 20 items, newest first — poll and dedupe.
    """
    import xml.etree.ElementTree as ET

    keywords = f"({source.get('search', 'financial analyst')})"
    if source.get("location_search"):
        keywords += f" AND locationSearch:({source['location_search']})"
    url = (
        f"https://{source['host']}/services/rss/job/?"
        + urllib.parse.urlencode({"locale": "en_US", "keywords": keywords})
    )
    root = ET.fromstring(http.get_text(url))
    jobs = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").split("?")[0]
        id_match = re.search(r"/(\d+)/?$", link)
        # Title carries location as a trailing "(City, Prov, CC, Postal)".
        location = ""
        loc_match = re.search(r"\(([^()]*)\)\s*$", title)
        if loc_match and ("," in loc_match.group(1)):
            location = loc_match.group(1)
            title = title[: loc_match.start()].strip()
        if not id_match or not title:
            continue
        jobs.append(
            Job(
                uid=f"sf:{source['host']}:{id_match.group(1)}",
                company=source.get("name", source["host"]),
                title=title,
                location=location,
                url=link,
            )
        )
    return jobs


def fetch_icims(source):
    """iCIMS Career Sites (formerly Jibe) public JSON API.
    Companies: KPMG Canada, Costco, ...

    source: host, query (optional; some hosts ignore it server-side),
    job_path (optional, default "/jobs/"), pages (optional)
    """
    jobs = []
    for page in range(1, source.get("pages", 1) + 1):
        params = {
            "page": str(page),
            "limit": "100",
            "sortBy": "posted_date",
            "descending": "true",
        }
        if source.get("query"):
            params["keywords"] = source["query"]
        if source.get("location"):
            params["location"] = source["location"]
        data = http.get_json(f"https://{source['host']}/api/jobs?" + urllib.parse.urlencode(params))
        page_jobs = data.get("jobs") or []
        if not page_jobs:
            break
        for j in page_jobs:
            d = j.get("data") or {}
            slug = d.get("slug", "")
            if not slug:
                continue
            location = ", ".join(x for x in [d.get("city"), d.get("state"), d.get("country")] if x)
            jobs.append(
                Job(
                    uid=f"icims:{source['host']}:{d.get('req_id') or slug}",
                    company=source.get("name", source["host"]),
                    title=d.get("title", ""),
                    location=location,
                    url=f"https://{source['host']}{source.get('job_path', '/jobs/')}{slug}",
                )
            )
    return jobs


def fetch_oracle(source):
    """Oracle Recruiting Cloud (ORC) public REST API.
    Companies: JPMorgan Chase, Lazard, ...

    source: host, site_number (e.g. "CX_1001"), search, location (optional),
    site_slug (optional, defaults to site_number), pages (optional)
    """
    jobs = []
    slug = source.get("site_slug", source["site_number"])
    for page in range(source.get("pages", 1)):
        finder = (
            f"findReqs;siteNumber={source['site_number']},limit=25,"
            f"offset={page * 25},keyword={urllib.parse.quote(source.get('search', 'financial analyst'))}"
        )
        if source.get("location"):
            finder += f",location={urllib.parse.quote(source['location'])}"
        # Without the expand param the API omits requisitionList entirely.
        url = (
            f"https://{source['host']}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
            f"?onlyData=true&expand=requisitionList&finder={finder}"
        )
        data = http.get_json(url)
        items = data.get("items") or [{}]
        reqs = items[0].get("requisitionList") or []
        if not reqs:
            break
        for j in reqs:
            jobs.append(
                Job(
                    uid=f"oracle:{source['host']}:{j.get('Id')}",
                    company=source.get("name", source["host"]),
                    title=j.get("Title", ""),
                    location=j.get("PrimaryLocation", "") or "",
                    url=f"https://{source['host']}/hcmUI/CandidateExperience/en/sites/{slug}/job/{j.get('Id')}",
                    posted=_day(j.get("PostedDate")),
                )
            )
        if len(reqs) < 25:
            break
    return jobs


# Cities scanned in Oleeo feed content to synthesize a location string —
# the Atom entries carry location only inside free-text description HTML.
OLEEO_CITIES = [
    "New York", "Toronto", "Vancouver", "Montreal", "Calgary", "San Francisco",
    "Los Angeles", "San Diego", "Menlo Park", "Palo Alto", "Chicago", "Houston",
    "Dallas", "Boston", "Charlotte", "Miami", "Washington", "Minneapolis",
    "Jersey City", "Philadelphia", "Stamford", "Greenwich", "Salt Lake City",
    "Austin", "Seattle", "Buffalo", "Ottawa", "Waterloo", "Kitchener",
    "London", "Paris", "Frankfurt", "Dubai", "Hong Kong", "Singapore", "Tokyo",
]


def fetch_pcsx(source):
    """Generic Eightfold PCSX search API (same engine as fetch_microsoft).
    Companies: Morgan Stanley, ...

    source: host, domain, query, location (optional), pages (optional)
    """
    jobs = []
    for page in range(source.get("pages", 2)):
        params = {
            "domain": source["domain"],
            "query": source.get("query", "financial analyst"),
            "start": str(page * 10),
            "num": "10",
            "sort_by": "relevance",
        }
        if source.get("location"):
            params["location"] = source["location"]
        data = http.get_json(f"https://{source['host']}/api/pcsx/search?" + urllib.parse.urlencode(params))
        positions = (data.get("data") or {}).get("positions") or []
        if not positions:
            break
        for j in positions:
            job_id = str(j.get("id", ""))
            path = j.get("positionUrl") or f"/careers/job/{job_id}"
            jobs.append(
                Job(
                    uid=f"pcsx:{source['host']}:{job_id}",
                    company=source.get("name", source["host"]),
                    title=j.get("name", ""),
                    location="; ".join(j.get("locations") or []),
                    url=f"https://{source['host']}{path}",
                    posted=_day(j.get("postedTs")),
                )
            )
        if len(positions) < 10:
            break
    return jobs



def fetch_dayforce(source):
    """Dayforce public job-feed API. Companies: eSentire, ...

    source: host (region host, e.g. can60.dayforcehcm.com), company (client
    namespace), country (optional ISO-2 client-side filter)
    """
    data = http.get_json(f"https://{source['host']}/Api/{source['company']}/V1/JobFeeds")
    jobs = []
    for j in data:
        if source.get("country") and j.get("Country") != source["country"]:
            continue
        location = ", ".join(x for x in [j.get("City"), j.get("State"), j.get("Country")] if x)
        jobs.append(
            Job(
                uid=f"dayforce:{source['company']}:{j.get('ReferenceNumber')}",
                company=source.get("name", source["company"]),
                title=j.get("Title", ""),
                location=location,
                url=j.get("JobDetailsUrl", ""),
                posted=_day(j.get("DatePosted")),
            )
        )
    return jobs


def fetch_smartrecruiters(source):
    """SmartRecruiters public postings API. Companies: ServiceNow, ...

    source: company (identifier), country (optional alpha-2), query (optional),
    limit (optional)
    """
    params = {"limit": str(source.get("limit", 100)), "offset": "0"}
    if source.get("country"):
        params["country"] = source["country"]
    if source.get("query"):
        params["q"] = source["query"]
    data = http.get_json(
        f"https://api.smartrecruiters.com/v1/companies/{source['company']}/postings?"
        + urllib.parse.urlencode(params)
    )
    jobs = []
    for j in data.get("content", []):
        loc = j.get("location") or {}
        location = loc.get("fullLocation") or ", ".join(
            x for x in [loc.get("city"), loc.get("region"), loc.get("country")] if x
        )
        jobs.append(
            Job(
                uid=f"smartrecruiters:{source['company']}:{j.get('id')}",
                company=source.get("name", source["company"]),
                title=j.get("name", ""),
                location=location,
                url=f"https://jobs.smartrecruiters.com/{source['company']}/{j.get('id')}",
                posted=_day(j.get("releasedDate")),
            )
        )
    return jobs


def fetch_jazzhr(source):
    """JazzHR hosted job board (applytojob.com). Companies: Xanadu, ...

    source: board (subdomain)
    """
    board = source["board"]
    html = http.get_text(f"https://{board}.applytojob.com/apply")
    jobs = []
    for m in re.finditer(
        rf'<a href="(https://{board}\.applytojob\.com/apply/([A-Za-z0-9]+)/[^"]*)"[^>]*>([\s\S]*?)</a>',
        html,
    ):
        url, job_id, inner = m.groups()
        title = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", inner)).strip().replace("&amp;", "&")
        if not title:
            continue
        window = html[m.end(): m.end() + 400]
        loc_m = re.search(r"map-marker[^>]*></i>\s*([^<]+)</li>", window)
        jobs.append(
            Job(
                uid=f"jazzhr:{board}:{job_id}",
                company=source.get("name", board),
                title=title,
                location=loc_m.group(1).strip().replace("&amp;", "&") if loc_m else "",
                url=url,
            )
        )
    return jobs


def fetch_ibm(source):
    """IBM in-house careers search (Elasticsearch proxy at www-api.ibm.com).

    source: query, country (optional, e.g. "Canada"), level (optional, e.g.
    "Entry Level"), size (optional)
    """
    filters = []
    if source.get("country"):
        filters.append({"term": {"field_keyword_05": source["country"]}})
    if source.get("level"):
        filters.append({"term": {"field_keyword_18": source["level"]}})
    payload = {
        "appId": "careers",
        "scopes": ["careers2"],
        "query": {
            "bool": {
                "must": [{"multi_match": {
                    "query": source.get("query", "software engineer"),
                    "fields": ["title", "description"],
                }}],
                "filter": filters,
            }
        },
        "size": source.get("size", 30),
        "from": 0,
        "_source": ["title", "url", "field_keyword_05", "field_keyword_18", "field_keyword_19"],
    }
    data = http.post_json_response("https://www-api.ibm.com/search/api/v2", payload)
    jobs = []
    for h in (data.get("hits") or {}).get("hits", []):
        s = h.get("_source") or {}
        jobs.append(
            Job(
                uid=f"ibm:{h.get('_id')}",
                company=source.get("name", "IBM"),
                title=s.get("title", ""),
                location=s.get("field_keyword_19", "") or s.get("field_keyword_05", ""),
                url=s.get("url", ""),
            )
        )
    return jobs


FETCHERS.update({
    "successfactors": fetch_successfactors,
    "icims": fetch_icims,
    "oracle": fetch_oracle,
    "pcsx": fetch_pcsx,
    "dayforce": fetch_dayforce,
    "smartrecruiters": fetch_smartrecruiters,
    "jazzhr": fetch_jazzhr,
    "ibm": fetch_ibm,
})

# Per-platform fix-ups applied to postings whose title matched, before the
# location filter. Each takes a Job and returns a Job.
RESOLVERS = {
    "workday": resolve_workday,
}
