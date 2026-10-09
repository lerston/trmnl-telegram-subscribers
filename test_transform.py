import copy
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("telegram_transform", Path(__file__).with_name("transform.py"))
plugin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plugin)
BASE = 1_800_000_000


def card(count="1 234 subscribers", title="Example Channel"):
    return f'<div class="tgme_page_title"><span>{title}</span></div><div class="tgme_page_extra">{count}</div>'


def input_for(channel="@example_channel", state=None, zone="UTC"):
    return {"trmnl": {"user": {"time_zone": zone}, "plugin_settings": {
        "custom_fields_values": {"channel": channel}}, "state": state or {}}}


class TelegramCounterTests(unittest.TestCase):
    def test_recipe_demo_is_explicit_and_never_saved_as_real_history(self):
        def forbidden(_):
            self.fail("Demo must not fetch a real channel")
        result = plugin.process(input_for(plugin.DEMO_CHANNEL), forbidden, BASE)
        self.assertEqual(result["status"], "demo")
        self.assertEqual(result["trmnl_state"], {})
        self.assertIn("fictional", result["note"])
        self.assertEqual(len(result["chart"]["points"]), 31)

    def test_channel_inputs(self):
        for value in ["Example_Channel", " @Example_Channel ", "https://t.me/Example_Channel/", "http://t.me/Example_Channel", "t.me/s/Example_Channel"]:
            self.assertEqual(plugin.normalize_channel(value), "example_channel")

    def test_reject_non_channel_urls(self):
        for value in ["", "https://evil.example/channel", "https://t.me@evil.example/a", "https://t.me/a/1", "https://t.me/+invite", "../channel", "tg://resolve?domain=example", "https://t.me/channel?q=1", "https://t.me:443/channel", "https://t.me/c/123"]:
            with self.subTest(value=value), self.assertRaises(plugin.SourceError):
                plugin.normalize_channel(value)

    def test_exact_count_and_html_entities(self):
        self.assertEqual(plugin.parse_card(card("9&#160;876&#8239;543 subscribers", "Design &amp; Code")), {"count": 9876543, "name": "Design & Code"})
        self.assertEqual(plugin.parse_card(card("0 subscribers"))["count"], 0)
        self.assertEqual(plugin.parse_card(card("1 subscriber"))["count"], 1)

    def test_never_invent_zero_or_expand_rounding(self):
        for count in ["1.2K subscribers", "2M subscribers", "123 members", "123 monthly users", "", "-1 subscribers", "subscribers"]:
            with self.subTest(count=count), self.assertRaises(plugin.SourceError):
                plugin.parse_card(card(count))
        with self.assertRaises(plugin.SourceError):
            plugin.parse_card('<div>123 subscribers</div>')

    def test_new_install_has_no_historical_deltas(self):
        result = plugin.process(input_for(), lambda _: {"count": 12, "name": "Example"}, BASE)
        self.assertEqual(result["subscribers"], 12)
        self.assertIsNone(result["delta_day"])
        self.assertIsNone(result["delta_week"])
        self.assertEqual(result["chart"]["segments"], [])

    def test_history_deltas_and_hour_deduplication(self):
        state = {}
        for hour in range(7 * 24 + 1):
            result = plugin.process(input_for(state=state), lambda _, h=hour: {"count": 1000 + h, "name": "Example"}, BASE + hour * plugin.HOUR)
            state = result["trmnl_state"]
        self.assertEqual(result["delta_day"], 24)
        self.assertEqual(result["delta_week"], 168)
        before = len(state["hours"])
        refreshed = plugin.process(input_for(state=state), lambda _: {"count": 1200, "name": "Example"}, BASE + 168 * plugin.HOUR + 30)
        self.assertEqual(len(refreshed["trmnl_state"]["hours"]), before)
        self.assertEqual(refreshed["subscribers"], 1200)

    def test_outage_preserves_last_success_without_new_point(self):
        state = plugin.process(input_for(), lambda _: {"count": 40, "name": "Example"}, BASE)["trmnl_state"]
        def unavailable(_):
            raise TimeoutError("never expose diagnostic payloads")
        result = plugin.process(input_for(state=state), unavailable, BASE + plugin.DAY)
        self.assertEqual(result["status"], "stale")
        self.assertEqual(result["trmnl_state"], state)
        self.assertEqual(result["subscribers"], 40)
        self.assertNotIn("diagnostic", result["note"])

    def test_change_channel_never_reuses_old_history(self):
        state = plugin.process(input_for(), lambda _: {"count": 40, "name": "Example"}, BASE)["trmnl_state"]
        result = plugin.process(input_for("@another_example", state), lambda _: {"count": 2, "name": "Other"}, BASE + plugin.DAY)
        self.assertEqual(len(result["trmnl_state"]["hours"]), 1)
        self.assertIsNone(result["delta_day"])
        self.assertEqual(result["channel"], "another_example")

    def test_missing_baseline_does_not_become_zero(self):
        state = plugin.process(input_for(), lambda _: {"count": 40, "name": "Example"}, BASE)["trmnl_state"]
        result = plugin.process(input_for(state=state), lambda _: {"count": 45, "name": "Example"}, BASE + 3 * plugin.DAY)
        self.assertIsNone(result["delta_day"])
        self.assertIsNone(result["delta_week"])
        self.assertEqual(len(result["chart"]["segments"]), 2)

    def test_bounded_month_history_with_large_channel_and_long_name(self):
        state = {}
        for hour in range(35 * 24):
            result = plugin.process(input_for(state=state), lambda _, h=hour: {"count": 9_000_000 + h, "name": "Я" * 128}, BASE + hour * plugin.HOUR)
            state = result["trmnl_state"]
        self.assertLessEqual(len(state["hours"]), plugin.MAX_HOURS)
        self.assertLessEqual(len(state["days"]), plugin.MAX_DAYS)
        self.assertLess(len(json.dumps(state, ensure_ascii=False).encode()), plugin.STATE_LIMIT)
        self.assertEqual(result["delta_week"], 168)

    def test_timezone_and_unknown_timezone(self):
        self.assertEqual(str(plugin.user_zone("bad/zone")), "UTC")
        result = plugin.process(input_for(zone="Europe/Moscow"), lambda _: {"count": 1, "name": "Example"}, BASE)
        self.assertEqual(result["timezone"], "Europe/Moscow")
        data = input_for(zone="Moscow")
        data["trmnl"]["user"]["time_zone_iana"] = "Europe/Moscow"
        self.assertEqual(plugin.process(data, lambda _: {"count": 1, "name": "Example"}, BASE)["timezone"], "Europe/Moscow")
        with patch.object(plugin, "ZoneInfo", side_effect=plugin.ZoneInfoNotFoundError()):
            self.assertEqual(plugin.user_zone("Europe/Moscow", 10800).utcoffset(None).total_seconds(), 10800)

    def test_corrupted_or_future_state(self):
        state = plugin.process(input_for(), lambda _: {"count": 40, "name": "Example"}, BASE)["trmnl_state"]
        bad = copy.deepcopy(state)
        bad["hours"] = "invalid"
        self.assertEqual(plugin.clean_state(bad, "example_channel"), {})
        result = plugin.process(input_for(state=state), lambda _: {"count": 9, "name": "Example"}, BASE - 10)
        self.assertEqual(result["status"], "stale")
        self.assertEqual(result["subscribers"], 40)

    def test_input_does_not_mutate_saved_state(self):
        state = plugin.process(input_for(), lambda _: {"count": 40, "name": "Example"}, BASE)["trmnl_state"]
        original = copy.deepcopy(state)
        plugin.process(input_for(state=state), lambda _: {"count": 41, "name": "Example"}, BASE + plugin.HOUR)
        self.assertEqual(state, original)

    def test_flat_chart_is_finite(self):
        result = plugin.chart([["2026-01-01", BASE, 10], ["2026-01-02", BASE + plugin.DAY, 10]])
        self.assertNotIn("nan", str(result))
        self.assertEqual(result["minimum"], result["maximum"])
        self.assertIn(",76.0", result["segments"][0])


if __name__ == "__main__":
    unittest.main()
