"""Persistence of previously-seen job identifiers.

State is a flat list of `Job.uid` strings stored as JSON. Identifiers are only
ever added, never removed: a posting disappearing from a feed should not cause
it to re-trigger a notification if it later reappears.
"""

import json
import os


def load_seen(path):
    """Load the set of previously-seen job uids (empty set if no state yet)."""
    if not os.path.exists(path):
        return set()
    with open(path) as f:
        return set(json.load(f))


def save_seen(path, uids):
    """Persist the given iterable of uids to disk (sorted for stable diffs)."""
    with open(path, "w") as f:
        json.dump(sorted(uids), f, indent=1)
