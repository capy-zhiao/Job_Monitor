"""Notification sinks: Discord and Slack incoming webhooks."""

import time

from . import http

DISCORD_EMBED_LIMIT = 10  # Discord allows at most 10 embeds per message
DISCORD_COLOR = 0x2ECC71


def _details(job):
    """Location, posting date and sponsorship as one short line."""
    parts = [job.location]
    if job.posted:
        parts.append(f"posted {job.posted}")
    if job.sponsors:
        parts.append("sponsors visas")
    return " · ".join(p for p in parts if p)


def notify_discord(webhook, jobs):
    """Post `jobs` to a Discord channel webhook as rich embeds."""
    for start in range(0, len(jobs), DISCORD_EMBED_LIMIT):
        batch = jobs[start:start + DISCORD_EMBED_LIMIT]
        payload = {
            "content": f"🔔 {len(jobs)} new job(s) found" if start == 0 else None,
            "embeds": [
                {
                    "title": f"{job.company}: {job.title}"[:256],
                    "url": job.url,
                    "description": _details(job)[:300],
                    "color": DISCORD_COLOR,
                }
                for job in batch
            ],
        }
        http.post_json(webhook, payload)
        time.sleep(1)  # stay well under Discord's rate limit


def notify_discord_text(webhook, text):
    """Post a plain message to a Discord webhook (Discord caps content at 2000 chars)."""
    http.post_json(webhook, {"content": text[:2000]})


def notify_slack(webhook, jobs):
    """Post `jobs` to a Slack incoming webhook as a single message."""
    lines = [
        f"• <{job.url}|{job.company}: {job.title}> ({_details(job)})" for job in jobs
    ]
    http.post_json(webhook, {"text": f"🔔 {len(jobs)} new job(s) found:\n" + "\n".join(lines)})
