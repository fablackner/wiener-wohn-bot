# wiener-wohn-bot 🏠

**Telegram (or email) notifications for new [Mein Wiener Wohn-Ticket](https://www.meinwohnticket.wien/) (Wohnberatung Wien / Wiener Wohnen) apartment listings.**

Vienna's subsidized-housing search has no notification service, so the only way to stay up to date is to keep opening the website and checking by hand. wiener-wohn-bot does that polling for you. It sends you a Telegram message for every **new** apartment, with a readable summary and the distance to a point you care about (your work, your family, …), and it can score each apartment with an AI model of your choice if you turn that on. This is purely a convenience: apartments aren't assigned first-come-first-served, so it just saves you from checking the page.

It runs hourly on **GitHub Actions** with no server needed. You can also run it with cron on your own machine (e.g. a Raspberry Pi).

## What you get

Each new apartment arrives as one message:

```
Wohnung 1220 Wien, Beispielgasse 12 | Score 87

SCORE: 87
Große, helle Wohnung im 4. Stock mit Loggia, nur 1,2 km vom Referenzpunkt entfernt.

URL: https://www.meinwohnticket.wien/wohnungen/...
Location URL: https://www.google.com/maps/place/...
Distance to Reference (m): 1200
1220 Wien, Beispielgasse 12
Größe/m²: 82,5
Zimmer: 3
Monatl. Kosten: 780,00
...
```

## How it works

wiener-wohn-bot is a single-shot script: each run logs in, fetches the current listing, compares the apartment IDs against `sent_apartments.txt`, and processes only IDs it hasn't seen before. You get exactly one message per apartment, however often it runs.

| Module | Purpose |
|--------|---------|
| `main.py` | Single-shot run: process only apartments not yet notified. |
| `auth.py` | Logs in with your username and password (Stadt Wien Konto SAML login). |
| `scraper.py` | Queries the site's GraphQL API for search results and apartment details; parses them; geocodes addresses. |
| `summary.py` | Builds a readable summary and computes the distance to your reference point. |
| `ai_client.py` | Optional AI 0–100 scoring with a short evaluation (any OpenAI-compatible provider). |
| `notifier.py` | Sends notifications to the enabled channels. |
| `telegram_client.py` | Sends Telegram messages via the Bot API. |
| `emailer.py` | Sends emails via SMTP (off by default). |
| `config.py` | Central configuration, loaded from `.env`. |

## Quick start

Requires [uv](https://docs.astral.sh/uv/) (it fetches a suitable Python automatically).

```bash
git clone https://github.com/fablackner/wiener-wohn-bot.git
cd wiener-wohn-bot

uv sync

cp .env.example .env
# edit .env: at minimum WB_USERNAME/WB_PASSWORD, the Telegram settings,
# your REF_LAT/REF_LON and your SEARCH_URL (see below)
```

**Login:** put your meinwohnticket.wien login (the Stadt Wien Konto at mein.wien.gv.at) into `WB_USERNAME` and `WB_PASSWORD`. The bot logs in by itself on every run. No more copying session cookies.

**Telegram:** create a bot with [@BotFather](https://t.me/BotFather) and put its token into `TELEGRAM_BOT_TOKEN`. Then send your bot any message, open `https://api.telegram.org/bot<TOKEN>/getUpdates`, and copy the number at `"chat":{"id":...}` into `TELEGRAM_CHAT_ID`. Several chat IDs can be comma separated, and a group chat works too.

**Search URL:** set up your filters (district, size, rooms, costs, …) at [meinwohnticket.wien/wohnungen](https://www.meinwohnticket.wien/wohnungen) and paste the URL from the address bar into `SEARCH_URL`. The bot reads the filters from it.

**Distance:** the site doesn't publish coordinates, so the bot looks up each address with the City of Vienna's open-data address service ([data.wien.gv.at](https://data.wien.gv.at/)).

Then test it without sending anything:

```bash
uv run main.py --dry-run     # prints message previews, sends nothing, writes no state
```

Record what's listed right now, so you only hear about apartments that appear from here on:

```bash
uv run main.py --mark-seen   # no messages, no applications
```

And run it for real:

```bash
uv run main.py               # notifies every new apartment, remembers what it sent
```

## Run on GitHub Actions (hourly)

The workflow in [`.github/workflows/check-apartments.yml`](.github/workflows/check-apartments.yml) runs the bot every hour (at minute 17; GitHub may start scheduled runs a few minutes late).

1. **Add your config as a secret.** Store your whole `.env` file as the repository secret `ENV_FILE`:
   ```bash
   gh secret set ENV_FILE < .env
   ```
   (Or in the browser: *Settings → Secrets and variables → Actions → New repository secret*, then paste the file's content.) Re-run this whenever you change `.env`.
2. **Seed the state** so the first run doesn't notify (and possibly apply to) everything currently listed. Under *Actions → Check apartments → Run workflow*, tick *Only record the current apartments as seen* and run it. If you already have a `sent_apartments.txt` from another machine, you can commit it to the `bot-state` branch instead.
3. That's it. Runs start every hour from then on, and *Run workflow* lets you trigger one manually.

**State:** the IDs of already-notified apartments are committed to the separate `bot-state` branch, so `main` stays clean. Delete a line there to be re-notified about that apartment.

**Privacy:** in a public repository, Actions logs are public, so the workflow only logs warnings and errors. Your `.env` secret is never printed.

**Keep in mind:** GitHub disables scheduled workflows in public repositories after 60 days without repository activity. It emails you beforehand, and one click under *Actions* re-enables it.

## Run with cron (e.g. on a Raspberry Pi)

Check once per hour:

```cron
17 * * * * cd /path/to/wiener-wohn-bot && /path/to/uv run main.py >> cron.log 2>&1
```

`.env` is loaded automatically, so cron needs no extra environment setup. State is kept in `sent_apartments.txt` next to the script. If you move between GitHub Actions and the Pi, copy that file along, or use `--mark-seen` on the new host first. Don't run both at the same time, or you'll get every message twice.

## Configuration

Everything is set in `.env`. See [`.env.example`](.env.example) for the full annotated list. The essentials:

| Variable | What it does |
|----------|--------------|
| `WB_USERNAME`, `WB_PASSWORD` | Your meinwohnticket.wien (Stadt Wien Konto) login. |
| `ENABLE_TELEGRAM`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Telegram notifications (on by default). |
| `ENABLE_EMAIL`, `EMAIL_SENDER`, `EMAIL_PASSWORD`, `EMAIL_RECIPIENTS`, `SMTP_SERVER`, `SMTP_PORT` | Email notifications (off by default). Any STARTTLS SMTP server works, and the default is GMX. |
| `REF_LAT`, `REF_LON` | Your reference point for the distance shown in every message. Defaults to Stephansplatz. |
| `ENABLE_AI`, `OPENAI_BASE_URL`, `OPENAI_API_KEY`, `OPENAI_MODEL` | Optional AI scoring with any OpenAI-compatible provider (see below). Without it, messages simply show "Score n/a". |
| `APT_EVAL_BASE_PROMPT` | The scoring prompt. Describe what *you* care about in an apartment. |
| `SEARCH_URL` | Your filtered search URL from meinwohnticket.wien. |

Errors (wrong password, the site being down, …) are sent to the same channels, so you notice when the bot stops working.

### AI scoring (optional)

With `ENABLE_AI=1`, each apartment is scored 0–100 based on your custom prompt. The score appears in the message's first line, so you can tell at a glance which listings are worth a closer look. If the AI is disabled, fails or takes longer than 60 seconds, you still get the full summary.

The bot talks to the AI through the OpenAI-compatible Chat Completions API, which nearly every provider supports. To switch provider, change three values in `.env`:

| Provider | `OPENAI_BASE_URL` | Example `OPENAI_MODEL` |
|----------|---------------|--------------------|
| OpenAI | `https://api.openai.com/v1` | `gpt-5-mini` |
| Gemini ([free key](https://aistudio.google.com/apikey)) | `https://generativelanguage.googleapis.com/v1beta/openai/` | `gemini-flash-lite-latest` |
| DeepInfra | `https://api.deepinfra.com/v1/openai` | `deepseek-ai/DeepSeek-V3` |
| OpenRouter | `https://openrouter.ai/api/v1` | `deepseek/deepseek-chat` |
| Ollama (local) | `http://localhost:11434/v1` | `llama3.2` (any `OPENAI_API_KEY`, e.g. `ollama`) |

`OPENAI_API_KEY` is the API key from that provider.

### Automatic application (optional, use with care ⚠️)

Wohnberatung Wien lets you have **three** active applications at a time. With `AUTOMATIC_APPLICATION=1`, wiener-wohn-bot submits an application on your account when an apartment meets **all** configured criteria:

- closer than `AUTO_MAX_DISTANCE_M` meters to your reference point
- larger than `AUTO_MIN_SIZE_SQM` m²
- at least on floor `AUTO_MIN_FLOOR_LEVEL`

If `CANCEL_APPLICATION_APT_ID` is set (the UUID from the apartment's URL, `meinwohnticket.wien/wohnungen/<UUID>`), the bot first cancels your existing application for that apartment (once per run) before applying to the new one.

**Be aware:** this performs real actions on your account. It's off by default. Test with `--dry-run` and generous criteria first, and check the log to see what would have triggered.

## Disclaimer

This is an unofficial hobby project, not affiliated with or endorsed by Wohnberatung Wien or the City of Vienna. It queries the website politely: one login per run, one search request per 24 results, and one detail request per *new* apartment, with a configurable delay. Use it responsibly and at your own risk, especially the automatic application feature. The website may change at any time and break the parser or the login.

## License

[MIT](LICENSE)
