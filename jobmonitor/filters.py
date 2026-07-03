"""Title and location matching used to keep only relevant postings."""


def matches(title, keywords, excludes):
    """Return True if `title` contains a keyword and none of the excludes.

    A trailing comma is appended to the title so that a keyword like
    ``"engineer i,"`` also matches a title that *ends* with "Engineer I"
    (e.g. "IT Developer I"). Matching is case-insensitive substring.
    """
    normalized = title.lower().strip() + ","
    if any(term.lower() in normalized for term in excludes):
        return False
    return any(keyword.lower() in normalized for keyword in keywords)


def location_ok(location, wanted):
    """Return True if `location` matches one of the `wanted` terms.

    An empty/omitted `wanted` list disables location filtering.
    """
    if not wanted:
        return True
    loc = (location or "").lower()
    return any(term.lower() in loc for term in wanted)
