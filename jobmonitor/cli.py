"""Command-line entry point: fetch, filter, diff against state, notify."""

import argparse
import os
import sys

from . import notify, state
from .fetchers import FETCHERS
from .filters import location_ok, matches

PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(PACKAGE_DIR)
DEFAULT_CONFIG = os.path.join(PROJECT_ROOT, "config.json")
DEFAULT_STATE = os.path.join(PROJECT_ROOT, "seen.json")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Poll company career APIs and push new matching jobs to Discord/Slack."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print matches only; send no webhook and do not update state",
    )
    parser.add_argument(
        "--notify-first",
        action="store_true",
        help="send notifications even on the very first run",
    )
    parser.add_argument("--config", default=DEFAULT_CONFIG, help="path to config.json")
    parser.add_argument("--state", default=DEFAULT_STATE, help="path to seen.json")
    return parser.parse_args(argv)


def collect_matches(config):
    """Fetch every source and return (matched_jobs, errors)."""
    import json

    with open(config) as f:
        cfg = json.load(f)

    matched, errors = [], []
    for source in cfg["sources"]:
        label = source.get("name", source["type"])
        try:
            jobs = FETCHERS[source["type"]](source)
        except Exception as exc:  # keep going if one source is down
            errors.append(f"{label}: {exc}")
            continue

        keywords = source.get("keywords", cfg["keywords"])
        excludes = source.get("exclude_keywords", cfg.get("exclude_keywords", []))
        locations = source.get("locations", cfg.get("locations"))
        hits = [
            job
            for job in jobs
            if matches(job.title, keywords, excludes)
            and location_ok(job.location, locations)
        ]
        print(f"[{label}] {len(jobs)} jobs fetched, {len(hits)} match keywords")
        matched.extend(hits)
    return matched, errors


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


def main(argv=None):
    args = parse_args(argv)

    first_run = not os.path.exists(args.state)
    seen = state.load_seen(args.state)

    matched, errors = collect_matches(args.config)
    new_jobs = [job for job in matched if job.uid not in seen]

    print(f"total matched: {len(matched)}, new since last run: {len(new_jobs)}")
    for job in new_jobs:
        print(f"  NEW: {job.company}: {job.title} ({job.location})\n       {job.url}")

    if args.dry_run:
        print("(dry run: no notifications sent, state not saved)")
        return

    if new_jobs and (not first_run or args.notify_first):
        send_notifications(new_jobs)
    elif first_run:
        print(f"first run: seeded {len(matched)} existing matches into state, no notifications")

    # Only ever add uids; a posting leaving a feed should not re-trigger later.
    seen.update(job.uid for job in matched)
    state.save_seen(args.state, seen)

    if errors:
        print("errors:\n  " + "\n  ".join(errors), file=sys.stderr)
        sys.exit(1 if not matched else 0)


if __name__ == "__main__":
    main()
