"""Discord bot with one slash command, /linkedin: search LinkedIn now and post the
entry-level results in the channel.

Runs on the owner's Mac rather than in GitHub Actions, because LinkedIn blocks
datacenter IPs. It keeps no state and never touches the repo, so it cannot
conflict with the scheduled monitor; it only reads the monitor's published
jobs.json to tell which results are already being tracked.

Token: ~/.config/linkedin-bot/token (or the LINKEDIN_BOT_TOKEN env var).
"""

import asyncio
import json
import os
import re
import sys
import urllib.request

import discord
from discord import app_commands

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from jobmonitor import http, linkedin  # noqa: E402

TOKEN_FILE = os.path.expanduser("~/.config/linkedin-bot/token")
LIVE_JOBS = "https://capy-zhiao.github.io/Job_Monitor/jobs.json"

PRESET = [
    "security engineer",
    "application security",
    "software engineer new grad",
    "software engineer entry level",
]

# Staffing agencies and job aggregators that re-post other companies' roles.
AGENCIES = [
    "ktek", "actalent", "hiredbuddy", "jobright", "dynamic connections", "randstad",
    "robert half", "teksystems", "insight global", "kforce", "hays", "procom",
    "jobot", "dice", "cybercoders", "lensa", "fdm group",
]


def load_excludes():
    with open(os.path.join(ROOT, "config.json")) as f:
        excludes = [e.lower() for e in json.load(f).get("exclude_keywords", [])]
    # French postings (Montreal) spell it with an accent.
    return excludes + ["sénior"]


def excluded(title, excludes):
    # Same convention as filters.matches: the trailing comma lets "ii," match
    # a title that ends in "II".
    normalized = title.lower().strip() + ","
    return any(e in normalized for e in excludes)


def company_key(name):
    words = re.sub(r"\([^)]*\)", " ", name.lower())
    words = re.sub(r"[^a-z0-9]+", " ", words).split()
    words = [w for w in words if w not in {"inc", "ltd", "llc", "corp", "the", "canada"}]
    return words[0] if words else ""


def title_key(title):
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def tracked_keys():
    """(company, title) pairs the scheduled monitor already reports."""
    try:
        req = urllib.request.Request(LIVE_JOBS, headers={"user-agent": http.USER_AGENT})
        with urllib.request.urlopen(req, timeout=20) as resp:
            jobs = json.loads(resp.read().decode("utf-8"))["jobs"]
    except Exception:
        return set()
    return {(company_key(j["company"]), title_key(j["title"])) for j in jobs}


def run_search(keywords, location, days):
    queries = [(keywords, location)] if keywords else [(q, location) for q in PRESET]
    jobs, error = linkedin.search(queries, days=days)
    excludes, tracked = load_excludes(), tracked_keys()
    fresh, already, dropped = [], 0, 0
    for job in jobs:
        if excluded(job.title, excludes) or any(a in job.company.lower() for a in AGENCIES):
            dropped += 1
        elif (company_key(job.company), title_key(job.title)) in tracked:
            already += 1
        else:
            fresh.append(job)
    return queries, fresh, already, dropped, error


intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)


@tree.command(name="linkedin", description="Search LinkedIn now and post entry-level matches")
@app_commands.describe(
    keywords="What to search for (default: security + software engineer presets)",
    location="Where (default: Canada)",
    days="Posted within",
)
@app_commands.choices(days=[
    app_commands.Choice(name="24 hours", value=1),
    app_commands.Choice(name="7 days", value=7),
    app_commands.Choice(name="14 days", value=14),
    app_commands.Choice(name="30 days", value=30),
])
async def linkedin_command(
    interaction: discord.Interaction,
    keywords: str = None,
    location: str = "Canada",
    days: app_commands.Choice[int] = None,
):
    # Searching takes longer than Discord's 3-second reply window, so defer first.
    await interaction.response.defer(thinking=True)
    window = days.value if days else 7
    loop = asyncio.get_running_loop()
    queries, fresh, already, dropped, error = await loop.run_in_executor(
        None, run_search, keywords, location, window
    )

    searched = ", ".join('"%s"' % q for q, _ in queries)
    header = "🔎 LinkedIn · %s · %s · last %d day%s\n**%d new** · %d already tracked by Job Monitor · %d skipped (senior / agency)" % (
        searched, location, window, "" if window == 1 else "s", len(fresh), already, dropped)
    if error:
        header += "\n⚠️ %s — showing what came back before that." % error
    if not fresh:
        await interaction.followup.send(header + "\nNothing new this time.")
        return

    embeds = [
        discord.Embed(
            title=("%s: %s" % (job.company, job.title))[:256],
            url=job.url,
            description=job.location[:200],
            color=0x0A66C2,
        )
        for job in fresh
    ]
    for start in range(0, len(embeds), 10):  # Discord allows 10 embeds per message
        await interaction.followup.send(content=header if start == 0 else None, embeds=embeds[start:start + 10])


@client.event
async def on_ready():
    # Guild commands appear immediately; global ones can take up to an hour.
    for guild in client.guilds:
        tree.copy_global_to(guild=guild)
        await tree.sync(guild=guild)
    print("ready as %s in %d server(s)" % (client.user, len(client.guilds)), flush=True)


@client.event
async def on_guild_join(guild):
    # on_ready only covers servers the bot was already in when it connected.
    tree.copy_global_to(guild=guild)
    await tree.sync(guild=guild)
    print("joined %s, /linkedin registered" % guild.name, flush=True)


def read_token():
    token = os.environ.get("LINKEDIN_BOT_TOKEN")
    if token:
        return token.strip()
    with open(TOKEN_FILE) as f:
        return f.read().strip()


if __name__ == "__main__":
    client.run(read_token())
