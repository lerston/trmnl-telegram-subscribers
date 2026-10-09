"""TRMNL Serverless entrypoint. No bot, credentials or third-party service."""

import json
import re
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

HOUR = 3600
DAY = 24 * HOUR
MAX_HOURS = 193
MAX_DAYS = 31
MAX_HTML_BYTES = 256 * 1024
STATE_LIMIT = 8192
DEMO_CHANNEL = "demo:telegram-subscribers"


class SourceError(ValueError):
    pass


def normalize_channel(value):
    value = str(value or "").strip()
    if value.startswith("@"):
        value = value[1:]
    elif "://" in value or value.lower().startswith("t.me/"):
        parsed = urlsplit(value if "://" in value else "https://" + value)
        if (parsed.scheme not in ("http", "https") or parsed.netloc.lower() != "t.me"
                or parsed.query or parsed.fragment):
            raise SourceError("Enter a public channel username or t.me channel address.")
        parts = parsed.path.strip("/").split("/")
        if len(parts) == 2 and parts[0] == "s":
            parts = parts[1:]
        if len(parts) != 1:
            raise SourceError("Use the channel address, not a post or invitation link.")
        value = parts[0]
    # Also allows short collectible usernames. Existence/type is checked by the card.
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_]{0,31}", value):
        raise SourceError("Enter a public channel username or t.me channel address.")
    if value.lower() in {"s", "share", "joinchat", "addstickers", "addemoji", "proxy", "login", "c"}:
        raise SourceError("Use a public channel address, not a Telegram service link.")
    return value.lower()


class CardParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.values = {"tgme_page_extra": [], "tgme_page_title": []}

    def handle_starttag(self, tag, attrs):
        if tag in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}:
            return
        classes = dict(attrs).get("class", "").split()
        self.stack.append((tag, next((c for c in classes if c in self.values), None)))

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        for name in {name for _, name in self.stack if name}:
            self.values[name].append(data)


def parse_card(html):
    parser = CardParser()
    parser.feed(html)
    extra = " ".join("".join(parser.values["tgme_page_extra"]).split())
    match = re.fullmatch(r"([0-9][0-9\s]*)\s+subscribers?", extra, re.IGNORECASE)
    if not match:
        raise SourceError("This page does not expose an exact public channel subscriber count.")
    count = int(re.sub(r"\s", "", match[1]))
    title = " ".join("".join(parser.values["tgme_page_title"]).split()).strip("✔ ")
    if not title or len(title) > 256:
        raise SourceError("Telegram did not return a valid channel card.")
    return {"count": count, "name": title}


class TelegramRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urlsplit(newurl)
        if parsed.scheme != "https" or parsed.netloc.lower() != "t.me":
            raise SourceError("Unexpected Telegram redirect.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_card(channel):
    request = Request("https://t.me/" + channel, headers={
        "User-Agent": "TRMNL-Telegram-Subscribers/1.0",
        "Accept": "text/html", "Accept-Language": "en",
    })
    with build_opener(TelegramRedirects()).open(request, timeout=3.5) as response:
        if response.status != 200:
            raise SourceError("Telegram is temporarily unavailable.")
        raw = response.read(MAX_HTML_BYTES + 1)
    if len(raw) > MAX_HTML_BYTES:
        raise SourceError("Telegram returned an unexpected page.")
    return parse_card(raw.decode("utf-8", errors="replace"))


def clean_state(state, channel):
    if not isinstance(state, dict) or state.get("channel") != channel or state.get("version") != 1:
        return {}
    try:
        if len(json.dumps(state, ensure_ascii=False).encode("utf-8")) > STATE_LIMIT:
            return {}
        if not isinstance(state.get("name"), str) or len(state["name"]) > 256:
            return {}
        if not isinstance(state.get("last_at"), int) or not isinstance(state.get("last_count"), int) or state["last_count"] < 0:
            return {}
        hours = state.get("hours", [])
        days = state.get("days", [])
        if len(hours) > MAX_HOURS or len(days) > MAX_DAYS:
            return {}
        if any(len(p) != 2 or any(type(v) is not int or v < 0 for v in p) for p in hours):
            return {}
        if any(len(p) != 3 or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", p[0])
               or any(type(v) is not int or v < 0 for v in p[1:]) for p in days):
            return {}
        if any(b[0] <= a[0] for a, b in zip(hours, hours[1:])):
            return {}
        if any(b[0] <= a[0] for a, b in zip(days, days[1:])):
            return {}
    except (TypeError, ValueError, KeyError):
        return {}
    return state


def user_zone(name, offset=None):
    try:
        return ZoneInfo(str(name or "UTC"))
    except (ZoneInfoNotFoundError, ValueError):
        # The hosted Python image may not include the IANA time-zone database.
        if type(offset) is int and -14 * HOUR <= offset <= 14 * HOUR:
            return timezone(timedelta(seconds=offset))
        return timezone.utc


def record(state, channel, card, now, zone):
    hours = [p for p in state.get("hours", []) if now - 8 * DAY <= p[0] < now]
    # Force Refresh or multiple renders in one hour must not fill the buffer.
    hours = [p for p in hours if p[0] // HOUR != now // HOUR]
    hours = (hours + [[now, card["count"]]])[-MAX_HOURS:]
    day = datetime.fromtimestamp(now, zone).strftime("%Y-%m-%d")
    # Time-zone edits re-bucket all available points using the new local date.
    daily = {}
    for _, at, count in state.get("days", []):
        if now - 31 * DAY <= at <= now:
            daily[datetime.fromtimestamp(at, zone).strftime("%Y-%m-%d")] = [at, count]
    for at, count in hours:
        daily[datetime.fromtimestamp(at, zone).strftime("%Y-%m-%d")] = [at, count]
    daily[day] = [now, card["count"]]
    days = [[date, *daily[date]] for date in sorted(daily)][-MAX_DAYS:]
    result = {"version": 1, "channel": channel, "name": card["name"],
              "last_at": now, "last_count": card["count"], "hours": hours, "days": days}
    if len(json.dumps(result, ensure_ascii=False).encode("utf-8")) > STATE_LIMIT:
        raise SourceError("History could not be saved.")
    return result


def delta(state, age):
    target = state["last_at"] - age
    candidates = [p for p in state.get("hours", []) if target - 2 * HOUR <= p[0] <= target]
    return state["last_count"] - max(candidates)[1] if candidates else None


def chart(days):
    if len(days) < 2:
        return {"segments": [], "areas": [], "points": [], "span_days": 0,
                "minimum": None, "maximum": None, "first_day": "", "last_day": ""}
    values = [p[2] for p in days]
    low, high = min(values), max(values)
    spread = max(high - low, 1)
    start, end = days[0][1], days[-1][1]
    segments, current, points = [], [], []
    previous = None
    for date, at, count in days:
        if previous is not None and (datetime.strptime(date, "%Y-%m-%d") - datetime.strptime(previous, "%Y-%m-%d")).days > 1:
            segments.append(" ".join(current))
            current = []
        x = 12 + 536 * (at - start) / max(end - start, 1)
        y = 76 if low == high else 132 - 112 * (count - low) / spread
        current.append(f"{x:.1f},{y:.1f}")
        points.append({"x": f"{x:.1f}", "y": f"{y:.1f}"})
        previous = date
    segments.append(" ".join(current))
    areas = [f'{part.split()[0].split(",")[0]},132 {part} {part.split()[-1].split(",")[0]},132'
             for part in segments if len(part.split()) > 1]
    span_days = (datetime.strptime(days[-1][0], "%Y-%m-%d") - datetime.strptime(days[0][0], "%Y-%m-%d")).days
    return {"segments": segments, "areas": areas, "points": points, "span_days": span_days, "minimum": low, "maximum": high,
            "first_day": days[0][0], "last_day": days[-1][0]}


def display(state, channel, zone, status, note=""):
    has_data = bool(state)
    updated = datetime.fromtimestamp(state["last_at"], zone) if has_data else None
    result = {"channel": channel, "channel_name": state.get("name", "Telegram Subscribers"),
              "has_data": has_data, "status": status, "note": note,
              "subscribers": state.get("last_count"), "subscribers_display": f'{state["last_count"]:,}' if has_data else "—",
              "updated_display": datetime.fromtimestamp(state["last_at"], zone).strftime("%d %b %H:%M") if has_data else "",
              "updated_date": updated.strftime("%d %b %Y") if updated else "",
              "updated_time": updated.strftime("%H:%M") if updated else "",
              "timezone": str(zone), "history_days": len(state.get("days", [])),
              "chart": chart(state.get("days", [])), "trmnl_state": state}
    for label, age in (("day", DAY), ("week", 7 * DAY)):
        value = delta(state, age) if has_data else None
        result["delta_" + label] = value
        result["delta_" + label + "_display"] = f"{value:+,}" if value is not None else "—"
    return result


def process(input_data, loader=fetch_card, now=None):
    trmnl = input_data.get("trmnl", {})
    fields = trmnl.get("plugin_settings", {}).get("custom_fields_values", {})
    user = trmnl.get("user", {})
    zone = user_zone(user.get("time_zone_iana") or user.get("time_zone"), user.get("utc_offset"))
    now = int(now if now is not None else datetime.now(timezone.utc).timestamp())
    # Recipe master only: visibly fictional preview, never saved as real history.
    if fields.get("channel") == DEMO_CHANNEL:
        hours = [[now - h * HOUR, 1386 - h // 5] for h in range(192, -1, -1)]
        days = [[datetime.fromtimestamp(now - d * DAY, zone).strftime("%Y-%m-%d"),
                 now - d * DAY, 1386 - d * 5] for d in range(30, -1, -1)]
        sample = {"name": "Example Channel", "last_at": now, "last_count": 1386,
                  "hours": hours, "days": days}
        result = display(sample, "example_channel", zone, "demo", "Demo · fictional data")
        result["trmnl_state"] = {}
        return result
    try:
        channel = normalize_channel(fields.get("channel"))
    except SourceError as exc:
        return display({}, "", zone, "invalid", str(exc))
    state = clean_state(trmnl.get("state", {}), channel)
    try:
        card = loader(channel)
        if type(card.get("count")) is not int or card["count"] < 0:
            raise SourceError("Telegram did not return an exact subscriber count.")
        if state and now < state["last_at"]:
            return display(state, channel, zone, "stale", "Waiting for the next update.")
        state = record(state, channel, card, now, zone)
        return display(state, channel, zone, "ok")
    except Exception:
        return display(state, channel, zone, "stale" if state else "unavailable",
                       "Could not read the public channel. Showing the last successful update." if state
                       else "No public channel counter found. Check the address or try again later.")


def run(input):
    return process(input)
