# Telegram Subscribers for TRMNL

Track a public Telegram channel's subscriber count and history on your TRMNL. Enter a channel username or `t.me` address. No bot, API key, Telegram login, or administrator access is required.

**Status: experimental.** The plugin is being tested and is not available in the TRMNL catalog. Source code is currently on the [testing branch](https://github.com/lerston/trmnl-telegram-subscribers/tree/codex/standalone), in [draft PR #1](https://github.com/lerston/trmnl-telegram-subscribers/pull/1).

## Features

- Current subscriber count and changes over 24 hours and 7 days.
- Up to 30 days of history, saved separately for each installation.
- Four layouts with newspaper typography and a dithered chart in the full and vertical layouts.
- Date and time of the last successful reading in your TRMNL time zone.
- Last known count retained when Telegram is temporarily unavailable.

## Installation for testing

Use Python 3.12 or 3.13 to build the import archive:

```sh
git clone --branch codex/standalone https://github.com/lerston/trmnl-telegram-subscribers.git
cd trmnl-telegram-subscribers
python -m venv .venv
```

Activate the environment with `.venv\Scripts\Activate.ps1` on Windows or `source .venv/bin/activate` on macOS/Linux, then run:

```sh
python -m pip install -r requirements-dev.txt
python build.py
```

1. Import the ZIP from `dist/` as a Private Plugin in TRMNL.
2. Check that Serverless uses Python and contains the code from `transform.py`. If the importer leaves it empty, paste the file into the Serverless editor.
3. Set **Public Telegram channel** to a username, `@username`, or `https://t.me/username`.
4. Refresh the plugin and check the server preview before adding it to your playlist.

History starts with the first successful reading. Until enough samples exist, the chart shows `Collecting history` and changes show a dash. Changing the channel resets its history.

## Limitations

- The data source is Telegram's public channel page, not an official analytics API. Page changes or availability issues can interrupt updates.
- Only public channels with an exact subscriber count are supported. Private channels, groups, personal accounts, and rounded counts are rejected.
- Updates run when the device requests them, at most once an hour. Infrequent display or device sleep can leave gaps in the history.
- Daily and weekly changes require a saved reading within two hours before the corresponding comparison time. Missing readings are not replaced with zero; the chart breaks across missing days.
- History contains snapshots of the total count, not individual joins and departures. Storage is limited to about eight days of hourly readings and 30 days of daily readings.
- Requires cloud TRMNL Serverless and Saved State. Terminus compatibility has not been tested.

## Development

See [CONTRIBUTING.md](https://github.com/lerston/trmnl-telegram-subscribers/blob/codex/standalone/CONTRIBUTING.md) for tests, previews, and contribution guidelines. Report bugs through [GitHub Issues](https://github.com/lerston/trmnl-telegram-subscribers/issues).

## TRMNL documentation

- [Importing and exporting Private Plugins](https://help.trmnl.com/en/articles/10542599-importing-and-exporting-private-plugins)
- [Serverless](https://help.trmnl.com/en/articles/14130649-serverless)
- [Saved State](https://help.trmnl.com/en/articles/16777795-saved-state)
- [On-demand plugin refresh](https://help.trmnl.com/en/articles/15123293-on-demand-plugin-refresh)
