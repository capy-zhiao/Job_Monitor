"""Command-line entry point: fetch, filter, diff against state, notify."""

import argparse
import dataclasses
import json
import os
import re
import sys
import urllib.parse
from datetime import date

from . import logos, notify, state
from .fetchers import FETCHERS, RESOLVERS
from .filters import location_ok, matches

PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(PACKAGE_DIR)
DEFAULT_CONFIG = os.path.join(PROJECT_ROOT, "config.json")
DEFAULT_STATE = os.path.join(PROJECT_ROOT, "seen.json")
DEFAULT_HEALTH = os.path.join(PROJECT_ROOT, "health.json")
DEFAULT_DOMAINS = os.path.join(PROJECT_ROOT, "company_domains.json")

# A source is reported once it has failed this many runs in a row, or has
# returned no postings at all for this many days.
FAIL_RUNS = 3
EMPTY_DAYS = 3


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Poll company career APIs and push new matching jobs to Discord/Slack."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print matches only; send no webhook, update no state and write no JSON",
    )
    parser.add_argument(
        "--notify-first",
        action="store_true",
        help="send notifications even on the very first run",
    )
    parser.add_argument("--config", default=DEFAULT_CONFIG, help="path to config.json")
    parser.add_argument("--state", default=DEFAULT_STATE, help="path to seen.json")
    parser.add_argument("--health", default=DEFAULT_HEALTH, help="path to health.json (per-source run history)")
    parser.add_argument(
        "--emit-json",
        metavar="PATH",
        help="write all currently-matched jobs to PATH as JSON (for the public jobs page)",
    )
    return parser.parse_args(argv)


def collect_matches(config):
    """Fetch every source and return (matched_jobs, report).

    `report` has one dict per source: name, ok, fetched, matched, and error
    when the fetch raised.
    """
    with open(config) as f:
        cfg = json.load(f)

    matched, report = [], []
    # One posting can surface through several sources (overlapping queries) or
    # repeat within one (Workday pagination echoes) — dedupe globally on uid.
    seen_uids = set()
    for source in cfg["sources"]:
        label = source.get("name", source["type"])
        try:
            jobs = FETCHERS[source["type"]](source)
        except Exception as exc:  # keep going if one source is down
            report.append({"name": label, "ok": False, "fetched": 0, "matched": 0, "error": str(exc)[:200]})
            continue

        keywords = source.get("keywords", cfg["keywords"])
        excludes = source.get("exclude_keywords", cfg.get("exclude_keywords", []))
        locations = source.get("locations", cfg.get("locations"))
        title_hits = [job for job in jobs if matches(job.title, keywords, excludes)]
        resolve = RESOLVERS.get(source["type"])
        if resolve:
            title_hits = [resolve(job) for job in title_hits]
        hits = [job for job in title_hits if location_ok(job.location, locations)]
        print(f"[{label}] {len(jobs)} jobs fetched, {len(hits)} match keywords")
        report.append({"name": label, "ok": True, "fetched": len(jobs), "matched": len(hits)})
        for job in hits:
            if job.uid not in seen_uids:
                seen_uids.add(job.uid)
                matched.append(job)
    return matched, report


# Query parameters that only say where a click came from
_TRACKING = {"ref", "source", "src", "gh_src", "lever-source", "lever-origin"}
_LIST_UIDS = ("ghlist:", "ghtable:")


def url_key(url):
    """The posting a URL points at, so one job listed by several sources can be
    recognised: host and path with tracking parameters dropped, and Greenhouse's
    two board hosts treated as one. Empty for an empty URL."""
    parts = urllib.parse.urlsplit((url or "").strip())
    if not parts.netloc:
        return ""
    host = re.sub(r"^www\.", "", parts.netloc.lower())
    if host in ("boards.greenhouse.io", "job-boards.greenhouse.io"):
        host = "greenhouse"
    query = sorted((k, v) for k, v in urllib.parse.parse_qsl(parts.query)
                   if not k.lower().startswith("utm_") and k.lower() not in _TRACKING)
    return host + parts.path.rstrip("/") + ("?" + urllib.parse.urlencode(query) if query else "")


def dedupe_by_url(jobs):
    """Keep one job per posting URL, in first-seen order.

    The same posting often arrives from its company's feed and from one or two
    community lists, each with its own uid and a reworded title. The company's
    copy wins because its title is the official one; a posting date or
    sponsorship flag only a list carries is kept. Reposts get a new URL, so
    they still come through.
    """
    groups = {}
    for job in jobs:
        groups.setdefault(url_key(job.url) or job.uid, []).append(job)
    out = []
    for group in groups.values():
        best = next((j for j in group if not j.uid.startswith(_LIST_UIDS)), group[0])
        out.append(dataclasses.replace(
            best,
            posted=best.posted or next((j.posted for j in group if j.posted), ""),
            sponsors=any(j.sponsors for j in group),
        ))
    return out


def update_health(path, report, today=None):
    """Record this run per source and return the lines worth telling the owner.

    A source is reported once when it has failed FAIL_RUNS runs in a row or has
    fetched nothing for EMPTY_DAYS days, and once more when it recovers. The
    record is kept in `path` between runs.
    """
    today = today or date.today().isoformat()
    try:
        with open(path) as f:
            history = json.load(f)
    except (OSError, ValueError):
        history = {}
    lines, updated = [], {}
    for r in report:
        h = history.get(r["name"], {})
        if not r["ok"]:
            h["fail_runs"] = h.get("fail_runs", 0) + 1
            h["last_error"] = r["error"]
            if h["fail_runs"] >= FAIL_RUNS and not h.get("reported_fail"):
                lines.append(f"⚠️ {r['name']} has failed {h['fail_runs']} runs in a row: {r['error']}")
                h["reported_fail"] = True
        else:
            if h.get("reported_fail"):
                lines.append(f"✅ {r['name']} is responding again")
            h.pop("reported_fail", None)
            h["fail_runs"] = 0
            h["last_ok"] = today
            if r["fetched"] == 0:
                h.setdefault("empty_since", today)
                days = (date.fromisoformat(today) - date.fromisoformat(h["empty_since"])).days
                if days >= EMPTY_DAYS and not h.get("reported_empty"):
                    lines.append(f"⚠️ {r['name']} has returned no postings at all since {h['empty_since']}")
                    h["reported_empty"] = True
            else:
                if h.get("reported_empty"):
                    lines.append(f"✅ {r['name']} is returning postings again")
                h.pop("empty_since", None)
                h.pop("reported_empty", None)
        updated[r["name"]] = h  # sources dropped from config fall out here
    with open(path, "w") as f:
        json.dump(updated, f, indent=1, sort_keys=True, ensure_ascii=False)
    return lines


def send_health(lines):
    """Post source-health lines to Discord, if a webhook is configured."""
    discord = os.environ.get("DISCORD_WEBHOOK_URL")
    if discord and lines:
        notify.notify_discord_text(discord, "Source health\n" + "\n".join(lines))


def send_notifications(new_jobs):
    """Dispatch `new_jobs` to whichever webhooks are configured in the env."""
    discord = os.environ.get("DISCORD_WEBHOOK_URL")
    slack = os.environ.get("SLACK_WEBHOOK_URL")
    if not discord and not slack:
        print("WARNING: new jobs found but no DISCORD_WEBHOOK_URL / SLACK_WEBHOOK_URL set")
    if discord:
        notify.notify_discord(discord, new_jobs)
        print(f"sent {len(new_jobs)} jobs to Discord")
    if slack:
        notify.notify_slack(slack, new_jobs)
        print(f"sent {len(new_jobs)} jobs to Slack")


def emit_jobs_json(path, matched, config_path=None, report=None):
    """Write the full current matched-job list (plus a first-seen date per
    posting, kept in a sidecar file) for the static jobs page."""
    from datetime import datetime, timezone

    def categorize(title):
        t = (title or "").lower()
        if any(k in t for k in ("security", "vulnerabilit", "appsec", "soc ", "soc analyst",
                                 "threat", "grc", "penetration", "infosec", "cryptograph")):
            return "Security"
        if any(k in t for k in ("machine learning", " ml ", "ml ", " ai ", "ai/", "llm",
                                 "deep learning", "applied scientist", "nlp", "data scientist")):
            return "AI/ML"
        if any(k in t for k in ("research engineer", "research scientist", "applied researcher",
                                 "researcher")):
            return "Research"
        if any(k in t for k in ("software", "developer", "sde", "full stack", "full-stack",
                                 "backend", "back end", "frontend", "front end", "systems engineer",
                                 "engineer")):
            return "SDE"
        return "Other"

    sidecar = os.path.join(os.path.dirname(os.path.abspath(path)), "first_seen.json")
    try:
        with open(sidecar) as f:
            first_seen = json.load(f)
    except (OSError, ValueError):
        first_seen = {}
    today = date.today().isoformat()
    for job in matched:
        # Keyed by uid and by URL, so a posting whose kept copy switches from a
        # community list to its company's feed keeps its first-seen day.
        key = "url:" + url_key(job.url) if url_key(job.url) else None
        day = first_seen.get(job.uid) or (first_seen.get(key) if key else None) or today
        first_seen[job.uid] = day
        if key:
            first_seen.setdefault(key, day)

    jobs = sorted(
        matched,
        key=lambda j: (j.posted or first_seen[j.uid], first_seen[j.uid], j.company, j.title),
        reverse=True,
    )
    stats, ca_terms = {}, []
    if config_path:
        try:
            with open(config_path) as f:
                cfg = json.load(f)
            srcs = cfg["sources"]
            stats = {"sources": len(srcs), "ats": len({s["type"] for s in srcs})}
            if report:
                stats["responded"] = sum(1 for r in report if r["ok"])
            ca_terms = [t.lower() for t in cfg.get("locations", [])]
        except (OSError, ValueError, KeyError):
            stats = {}

    # Company icons: the page shows the source's company without its suffix
    # ("TD (Security)" -> "TD"), with the icon of the domain mapped to it.
    domains_path = os.path.join(os.path.dirname(os.path.abspath(config_path)), "company_domains.json") \
        if config_path else DEFAULT_DOMAINS
    domain_of = logos.load_domains(domains_path)
    wanted = {domain_of[logos.base_company(j.company)] for j in jobs if logos.base_company(j.company) in domain_of}
    icon_of = logos.ensure_logos(wanted, os.path.join(os.path.dirname(os.path.abspath(path)), "logos"))

    def logo(job):
        name = icon_of.get(domain_of.get(logos.base_company(job.company), ""))
        return {"logo": "logos/" + name} if name else {}

    payload = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "count": len(jobs),
        "stats": stats,
        "jobs": [
            {
                "company": logos.base_company(j.company) or j.company,
                **logo(j),
                "title": j.title,
                "location": j.location,
                "url": j.url,
                "first_seen": first_seen[j.uid],
                **({"posted": j.posted} if j.posted else {}),
                **({"sponsors": True} if j.sponsors else {}),
                "category": categorize(j.title),
            }
            for j in jobs
        ],
    }
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w") as f:
        json.dump(payload, f, indent=1, ensure_ascii=False)
    with open(sidecar, "w") as f:
        json.dump(first_seen, f, indent=0, sort_keys=True)

    # Daily history snapshot: one entry per day, upserted so multiple same-day
    # runs keep only the latest count. Kept to ~90 days. The page no longer
    # charts it, but the series is still recorded.
    hist_path = os.path.join(os.path.dirname(os.path.abspath(path)), "history.json")
    by_cat = {}
    for j in jobs:
        c = categorize(j.title)
        by_cat[c] = by_cat.get(c, 0) + 1
    try:
        with open(hist_path) as f:
            history = json.load(f)
    except (OSError, ValueError):
        history = []
    # "ca" gives one continuous series: the feed was
    # Canada-only until US new-grad roles were added on 2026-09-28, so earlier
    # snapshots' totals are Canadian counts.
    ca_count = sum(1 for j in jobs if any(t in (j.location or "").lower() for t in ca_terms))
    for h in history:
        h.setdefault("ca", h["total"])
    history = [h for h in history if h.get("date") != today]
    history.append({"date": today, "total": len(jobs), "ca": ca_count, "by": by_cat})
    history = sorted(history, key=lambda h: h["date"])[-90:]
    with open(hist_path, "w") as f:
        json.dump(history, f, indent=0, ensure_ascii=False)

    print(f"emitted {len(jobs)} jobs to {path}")


def main(argv=None):
    args = parse_args(argv)

    first_run = not os.path.exists(args.state)
    seen = state.load_seen(args.state)

    matched, report = collect_matches(args.config)
    errors = [f"{r['name']}: {r['error']}" for r in report if not r["ok"]]

    # A posting can arrive under several uids (its company's feed and community
    # lists). It counts as seen if any of them was, or if its URL was recorded.
    all_uids = [job.uid for job in matched]
    seen_urls = {k for k in seen if k.startswith("url:")}
    seen_urls |= {"url:" + url_key(j.url) for j in matched if j.uid in seen and url_key(j.url)}
    matched = dedupe_by_url(matched)
    new_jobs = [
        job for job in matched
        if job.uid not in seen and "url:" + url_key(job.url) not in seen_urls
    ]

    if args.emit_json and not args.dry_run:
        emit_jobs_json(args.emit_json, matched, args.config, report)

    print(f"total matched: {len(matched)}, new since last run: {len(new_jobs)}")
    for job in new_jobs:
        print(f"  NEW: {job.company}: {job.title} ({job.location})\n       {job.url}")

    if args.dry_run:
        print("(dry run: no notifications sent, state and JSON not written)")
        return

    if new_jobs and (not first_run or args.notify_first):
        send_notifications(new_jobs)
    elif first_run:
        print(f"first run: seeded {len(matched)} existing matches into state, no notifications")

    # Only ever add uids; a posting leaving a feed should not re-trigger later.
    seen.update(all_uids)
    seen.update("url:" + url_key(job.url) for job in matched if url_key(job.url))
    state.save_seen(args.state, seen)

    health = update_health(args.health, report)
    if health:
        print("source health:\n  " + "\n  ".join(health))
        send_health(health)

    if errors:
        print("errors:\n  " + "\n  ".join(errors), file=sys.stderr)
        sys.exit(1 if not matched else 0)


if __name__ == "__main__":
    main()
