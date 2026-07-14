# wiener-wohn-bot 🏠

**Email notifications for new [Wohnberatung Wien / Wiener Wohnen](https://wohnungssuche.wohnberatung-wien.at/) apartment listings.**

Vienna's subsidized-housing search has no notification service, so the only way to stay up to date is to keep opening the website and checking by hand. wiener-wohn-bot does that polling for you: it emails you every **new** apartment with a readable summary and the distance to a point you care about (your work, your family, …), and can optionally score each apartment with Gemini AI. Purely a convenience — the apartments aren't assigned first-come-first-served, this just saves you the routine of checking the page.

## What you get

Each new apartment arrives as one email:

```
Subject: Wohnung 1220 Wien, Beispielgasse 12 | Score 87

SCORE: 87
Große, helle Wohnung im 4. Stock mit Loggia, nur 1,2 km vom Referenzpunkt entfernt.

URL: https://wohnungssuche.wohnberatung-wien.at/?page=wohnung&id=...
Location URL: https://www.google.com/maps/place/...
Distance to Reference (m): 1200
1220 Wien, Beispielgasse 12
Größe/m²: 82,5
Zimmer: 3
Monatl. Kosten: 780,00
...
```

## How it works

wiener-wohn-bot is a single-shot script made for cron: each run fetches the current listing, compares the apartment IDs against `sent_apartments.txt`, and processes only IDs it hasn't seen before — so you get exactly one email per apartment, no matter how often it runs.

| Module | Purpose |
|--------|---------|
| `main.py` | Single-shot run: process only apartments not yet emailed. |
| `scraper.py` | Fetches the listing and apartment detail pages; parses them. |
| `summary.py` | Builds a readable summary and computes the distance to your reference point. |
| `ai_client.py` | Optional Gemini-based 0–100 scoring with a short evaluation. |
| `emailer.py` | Sends notification and error emails via SMTP. |
| `config.py` | Central configuration, loaded from `.env`. |

## Quick start

Requires Python 3.10+.

```bash
git clone https://github.com/fablackner/wiener-wohn-bot.git
cd wiener-wohn-bot

python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# edit .env: at minimum the email settings, your REF_LAT/REF_LON,
# and your session cookies (see below)
```

**Session cookies:** the search results are only visible when logged in, so the bot reuses your browser session. Log in at [wohnungssuche.wohnberatung-wien.at](https://wohnungssuche.wohnberatung-wien.at/), open the developer tools (F12 → Application/Storage → Cookies), and copy `PHPSESSID` and `StickySession` into `WB_COOKIE_PHPSESSID` and `WB_COOKIE_StickySession` in your `.env`. When the session expires, the bot finds 0 apartments and logs a warning — log in again and refresh the values.

Then test it without sending anything:

```bash
python main.py --dry-run   # prints email previews, sends nothing, writes no state
```

And run it for real:

```bash
python main.py             # emails every new apartment, remembers what it sent
```

## Automate with cron

Let it check every 10 minutes:

```cron
*/10 * * * * cd /path/to/wiener-wohn-bot && /path/to/wiener-wohn-bot/.venv/bin/python main.py >> cron.log 2>&1
```

`.env` is loaded automatically, so no extra cron environment setup is needed. The first real run emails everything currently listed; after that you only hear about new apartments.

## Configuration

Everything is set in `.env` — see [`.env.example`](.env.example) for the full annotated list. The essentials:

| Variable | What it does |
|----------|--------------|
| `EMAIL_SENDER`, `EMAIL_PASSWORD`, `EMAIL_RECIPIENTS` | SMTP account to send from and who gets notified (comma separated). |
| `SMTP_SERVER`, `SMTP_PORT` | Defaults to GMX (`mail.gmx.net:587`); any STARTTLS SMTP server works. |
| `REF_LAT`, `REF_LON` | Your reference point for the distance shown in every email. Defaults to Stephansplatz. |
| `ENABLE_AI`, `GEMINI_API_KEY` | Optional AI scoring (free API key from [Google AI Studio](https://aistudio.google.com/apikey)). Without it, emails simply show "Score n/a". |
| `APT_EVAL_BASE_PROMPT` | The scoring prompt — describe what *you* care about in an apartment. |
| `WB_COOKIE_*` | Session cookies from your logged-in browser session; required to see search results and for auto-application. |

### AI scoring (optional)

With `ENABLE_AI=1` and a Gemini API key, each apartment is scored 0–100 based on your custom prompt, and the score appears in the email subject — so you can tell at a glance which listings are worth a closer look. If the AI is disabled or fails, you still get the full summary email.

### Automatic application (optional, use with care ⚠️)

Wohnberatung Wien lets you have **three** active applications at a time. With `AUTOMATIC_APPLICATION=1`, wiener-wohn-bot submits an application on your account when an apartment meets **all** configured criteria:

- closer than `AUTO_MAX_DISTANCE_M` meters to your reference point
- larger than `AUTO_MIN_SIZE_SQM` m²
- at least on floor `AUTO_MIN_FLOOR_LEVEL`

If `CANCEL_APPLICATION_APT_ID` is set, the bot first cancels this existing application for that apartment (once per run) before applying to the new one.

**Be aware:** this performs real actions on your account using your session cookies. It's off by default — test with `--dry-run` and generous criteria first, and check `logfile.log` to see what would have triggered.

## State and duplicates

Sent apartment IDs live in `sent_apartments.txt`, one per line. Delete a line to get re-notified about that apartment; delete the file to start fresh.

## Disclaimer

This is an unofficial hobby project, not affiliated with or endorsed by Wohnberatung Wien or the City of Vienna. It politely scrapes the website (one listing request plus one request per *new* apartment, with a configurable delay). Use it responsibly and at your own risk — especially the automatic application feature. The website may change at any time and break the parser.

## License

[MIT](LICENSE)
