"""Core data model shared across fetchers, filters, and notifiers."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Job:
    """A single job posting, normalized across every source platform.

    `uid` is a stable, globally-unique identifier (``"<platform>:<...>"``) used
    for deduplication against previously-seen jobs. `posted` is the day the
    employer published the posting (``YYYY-MM-DD``) when the source reports it,
    else empty. `sponsors` is True when the source says the employer sponsors
    work visas (only the community lists report this).
    """

    uid: str
    company: str
    title: str
    location: str = ""
    url: str = ""
    employment_type: str = ""
    posted: str = ""
    sponsors: bool = False
