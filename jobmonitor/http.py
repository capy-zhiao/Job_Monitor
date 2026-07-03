"""Thin HTTP helpers built on urllib (no third-party dependencies)."""

import json
import urllib.request

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
)

TIMEOUT = 30


def get_json(url):
    """GET a URL and parse the response body as JSON."""
    req = urllib.request.Request(
        url, headers={"user-agent": USER_AGENT, "accept": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_text(url):
    """GET a URL and return the raw response body as text."""
    req = urllib.request.Request(url, headers={"user-agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read().decode("utf-8", errors="replace")


def post_json(url, payload):
    """POST a JSON payload and return the raw response bytes."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "user-agent": USER_AGENT,
            "content-type": "application/json",
            "accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read()


def post_json_response(url, payload):
    """POST a JSON payload and parse the response body as JSON."""
    return json.loads(post_json(url, payload).decode("utf-8"))
