"""Company icons for the jobs page.

Most postings link to an applicant tracking system (Greenhouse, Workday, ...),
so the company's own domain cannot be read off the job URL. `company_domains.json`
maps each company name to its domain by hand; a company missing from it shows
its initial on the page instead of an icon, which is better than a wrong logo.

Each domain's favicon is fetched once, at 64 px, and kept in ``docs/logos/`` so
the page serves the icons itself and visitors' browsers never call a
third-party icon service.
"""

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

from . import http

FAVICON_URL = "https://www.google.com/s2/favicons?domain={domain}&sz=64"
# The icon service answers with PNG or JPEG; the file extension follows the bytes.
SIGNATURES = {b"\x89PNG\r\n\x1a\n": ".png", b"\xff\xd8\xff": ".jpg"}


def base_company(name):
    """The company a source is named after: "TD (Security)" -> "TD"."""
    return re.sub(r"\s*\([^)]*\)\s*$", "", name or "").strip()


def load_domains(path):
    """Company name -> domain, or {} if the file is missing or unreadable."""
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _image_type(body):
    return next((ext for sig, ext in SIGNATURES.items() if body.startswith(sig)), None)


def fetch_icon(domain):
    """The domain's favicon as (bytes, extension), or None when it has none (the
    icon service answers 404 with a generic globe) or the request fails. Some
    sites only answer on "www.", so that is tried second."""
    for host in (domain, "www." + domain):
        req = urllib.request.Request(
            FAVICON_URL.format(domain=urllib.parse.quote(host)), headers={"user-agent": http.USER_AGENT}
        )
        try:
            with urllib.request.urlopen(req, timeout=http.TIMEOUT) as resp:
                body = resp.read()
        except (urllib.error.URLError, OSError):
            continue
        ext = _image_type(body)
        if ext:
            return body, ext
    return None


def ensure_logos(domains, logo_dir, fetch=fetch_icon):
    """Make sure every domain in `domains` has an icon in `logo_dir`, fetching
    only the ones not already there. Returns {domain: file name} for the
    domains that have an icon."""
    os.makedirs(logo_dir, exist_ok=True)
    have = {}
    for domain in sorted(set(domains)):
        name = next((domain + ext for ext in SIGNATURES.values()
                     if os.path.exists(os.path.join(logo_dir, domain + ext))), None)
        if not name:
            got = fetch(domain)
            if not got:
                continue
            body, ext = got
            name = domain + ext
            with open(os.path.join(logo_dir, name), "wb") as f:
                f.write(body)
        have[domain] = name
    return have
