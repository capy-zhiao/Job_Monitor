"""Title and location matching used to keep only relevant postings."""

import re

# Levels above entry anywhere in the title ("Software Engineer II - Backend",
# "Cloud Engineer 2, Site Reliability Engineering"). The " ii," style excludes
# only catch a level at the very end of a title. "Level 3" is left alone
# because companies such as Snap and Google use it for new grads.
_LEVEL = re.compile(
    r"\b(?:ii|iii|iv)\b"
    r"|\b(?:engineer|developer|programmer|analyst|scientist)\s*,?\s*[2-9]\b"
    r"|\bresearcher\s*[3-9]\b",
    re.I,
)
# ...unless the title says it is an early-career role ("SE II, New Grad").
_EARLY_CAREER = re.compile(r"new grad|new college grad|graduate|university|college|early career|entry.level|campus", re.I)

# A year keyword ("2027") says when, not what: on its own it let in "Finance
# Intern - Winter 2027" and "Content Design Intern (Summer 2027)". A title that
# matches only a year must also name technical work.
_YEAR = re.compile(r"^20\d\d$")
_TECHNICAL = re.compile(
    r"engineer|developer|development|software|programm|security|cyber|devops|cloud|platform|"
    r"infrastructure|systems|machine learning|\bml\b|\bai\b|data scien|research|scientist|"
    r"\bsre\b|back.?end|front.?end|full.?stack|architect|technolog|computer|\bit\b|quant|"
    r"d[ée]velopp|logiciel|informatique|s[ée]curit",
    re.I,
)


def matches(title, keywords, excludes):
    """Return True if `title` contains a keyword and none of the excludes.

    A trailing comma is appended to the title so that a keyword like
    ``"engineer i,"`` also matches a title that *ends* with "Engineer I"
    (e.g. "IT Developer I"). Matching is case-insensitive substring. On top of
    the excludes, titles above entry level are dropped unless they say they are
    early-career or a keyword names that level itself (a source may list
    "engineer 2" on purpose), and a match on a year alone needs a technical word.
    """
    normalized = title.lower().strip() + ","
    if any(term.lower() in normalized for term in excludes):
        return False
    hits = [keyword for keyword in keywords if keyword.lower() in normalized]
    if not hits:
        return False
    if (_LEVEL.search(title) and not _EARLY_CAREER.search(title)
            and not any(_LEVEL.search(keyword) for keyword in hits)):
        return False
    if all(_YEAR.match(keyword.strip()) for keyword in hits):
        return bool(_TECHNICAL.search(title))
    return True


def location_ok(location, wanted):
    """Return True if `location` matches one of the `wanted` terms.

    An empty/omitted `wanted` list disables location filtering.
    """
    if not wanted:
        return True
    loc = (location or "").lower()
    return any(term.lower() in loc for term in wanted)
