"""Core data model shared across fetchers, filters, and notifiers."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Job:
    """A single job posting, normalized across every source platform.

    `uid` is a stable, globally-unique identifier (``"<platform>:<...>"``) used
    for deduplication against previously-seen jobs.
    """

    uid: str
    company: str
    title: str
    location: str = ""
    url: str = ""
    employment_type: str = ""
