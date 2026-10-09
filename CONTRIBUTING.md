# Contributing

Use a `codex/<name>` branch and a pull request for code, Liquid templates, settings, and integration changes. Keep documentation, comments, and user-facing text in English.

## Local checks

Use Python 3.12 or 3.13 with the dependencies in `requirements-dev.txt`:

```sh
python -m pip install -r requirements-dev.txt
python -m unittest discover -s . -p "test_*.py"
python build.py
```

The build writes an importable ZIP and four HTML preview scenarios to the ignored `dist/` directory: sample history, first reading, unavailable channel, and a large count with a long title. Each preview includes all four layouts.

Tests use fictional data and make no Telegram or TRMNL requests. The `demo:telegram-subscribers` channel value also produces fictional data without fetching Telegram or saving history; use it only for development.

CI runs the tests and build on both supported Python versions. A local preview does not verify TRMNL's server rendering or the physical e-ink display. In the PR, distinguish local checks, cloud previews, and device checks; mark anything untested explicitly.

## Project files

- `transform.py`: channel validation, public-page parsing, saved history, and chart data.
- `settings.yml`: plugin settings and the channel input field.
- `shared.liquid` and the four layout templates: display markup and styles.
- `test_transform.py`: parsing, history, error handling, and layout checks.
- `build.py`: import archive and fictional previews.
- `icon.svg`: plugin icon.

Review the full diff before submitting. Do not commit credentials, tokens, webhook URLs, private channel data, device dumps, saved production state, or local network addresses. Keep generated files and virtual environments out of version control.
