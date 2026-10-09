# /linkedin Discord bot

A slash command for the job-alert Discord server: type `/linkedin` and the bot
searches LinkedIn's public job listings right then, drops senior titles and
staffing agencies, skips anything the scheduled monitor already reports, and
posts the rest in the channel.

![/linkedin results in Discord](linkedin.png)

```
/linkedin                                   # preset security + new-grad SWE searches, Canada, last 7 days
/linkedin keywords:"backend engineer"       # your own search
/linkedin keywords:"security engineer" location:"Seattle, Washington, United States" days:14 days
```

## Why it runs locally instead of in GitHub Actions

LinkedIn blocks requests from datacenter IPs such as GitHub's runners, and its
terms don't allow automated scraping. So this is on demand and low volume, from
a home connection, and it is deliberately separate from the scheduled monitor:
it keeps no state and never writes to the repo, so the two can't conflict. It
only reads the monitor's published `docs/jobs.json` to recognise jobs that are
already being tracked.

The LinkedIn search itself lives in `jobmonitor/linkedin.py` (standard library
only); this folder adds the Discord layer, which needs `discord.py`.

## Setup

1. **Create the bot.** At <https://discord.com/developers/applications>, create
   an application, open **Bot**, and click **Reset Token**, then copy the token.
2. **Store the token** without pasting it anywhere else:
   ```bash
   mkdir -p ~/.config/linkedin-bot && pbpaste > ~/.config/linkedin-bot/token && chmod 600 ~/.config/linkedin-bot/token
   ```
3. **Invite it.** Under **OAuth2 → URL Generator**, tick the `bot` and
   `applications.commands` scopes and the *Send Messages* and *Embed Links*
   permissions, open the generated URL and pick your server.
4. **Install and run:**
   ```bash
   python3 -m venv discord_bot/.venv
   discord_bot/.venv/bin/pip install "discord.py>=2.4"
   discord_bot/.venv/bin/python discord_bot/linkedin_bot.py
   ```
   On macOS a LaunchAgent keeps it running across logins and restarts it if it
   crashes; the command only answers while the computer is awake.
