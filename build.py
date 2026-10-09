"""Build a flat TRMNL archive and local mock previews; never writes live data."""
import json
from html import escape
from pathlib import Path
import zipfile
from liquid import Environment, DictLoader
from transform import process, DAY

ROOT = Path(__file__).resolve().parent
LAYOUTS = {"full": (800, 480), "half_horizontal": (800, 240),
           "half_vertical": (400, 480), "quadrant": (400, 240)}
FILES = ["settings.yml", "transform.py", "shared.liquid", *[name + ".liquid" for name in LAYOUTS]]


def mock_data():
    state = {}
    start = 1_790_064_000
    for hour in range(30 * 24):
        count = 1240 + hour // 5 + (hour // 24 % 5) - (hour // 36 % 3)
        result = process({"trmnl": {"state": state, "user": {"time_zone": "UTC"},
            "plugin_settings": {"custom_fields_values": {"channel": "@example_channel"}}}},
            lambda _, n=count: {"name": "Example Channel", "count": n}, start + hour * 3600)
        state = result["trmnl_state"]
    return result


def environment(shared):
    env = Environment(loader=DictLoader({}))
    env.add_filter("number_with_delimiter", lambda x: f"{int(x):,}" if x is not None else "—")
    # TRMNL's named template tags are not part of standard Liquid.
    import re
    templates = dict(re.findall(r'{% template (\w+) %}(.*?){% endtemplate %}', shared, re.DOTALL))
    env.loader = DictLoader(templates)
    return env


def build():
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    archive = dist / "telegram-subscribers.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zipped:
        for name in FILES:
            zipped.writestr(name, (ROOT / name).read_bytes())
    env = environment((ROOT / "shared.liquid").read_text(encoding="utf-8"))
    data = mock_data()
    states = {"demo": data, "first-update": process({"trmnl": {"plugin_settings": {"custom_fields_values": {"channel": "example_channel"}}}}, lambda _: {"name": "Example Channel", "count": 12}, 1_790_064_000),
              "unavailable": process({"trmnl": {"plugin_settings": {"custom_fields_values": {"channel": "example_channel"}}}}, lambda _: (_ for _ in ()).throw(TimeoutError())),
              "large-channel": {**data, "channel_name": "A channel with a very long descriptive title for layout testing", "subscribers_display": "9,876,543"}}
    styles = '<link rel="stylesheet" href="https://trmnl.com/css/3.4.0/plugins.css"><script src="https://trmnl.com/js/3.4.0/plugins.js"></script>'
    for scenario, variables in states.items():
        pieces = []
        for name, (width, height) in LAYOUTS.items():
            content = env.from_string((ROOT / (name + ".liquid")).read_text(encoding="utf-8")).render(**variables)
            pieces.append(f'<h2>{name}</h2><div style="width:{width}px;height:{height}px;overflow:hidden"><div class="screen"><div class="view view--{name}">{content}</div></div></div>')
        html = '<!doctype html><html><head><meta charset="utf-8"><title>Telegram Subscribers — fictional preview</title>' + styles + '</head><body class="environment trmnl"><p>Fictional local preview. Server rendering and physical device are not verified.</p>' + ''.join(pieces) + '</body></html>'
        (dist / ("preview-" + scenario + ".html")).write_text(html, encoding="utf-8")
    (dist / "demo.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    sources = '<html><head><meta charset="utf-8"><title>Authored plugin source</title></head><body>'
    for name in FILES:
        sources += f'<h2>{name}</h2><pre id="{name}">{escape((ROOT / name).read_text(encoding="utf-8"))}</pre>'
    (dist / "source.html").write_text(sources + '</body></html>', encoding="utf-8")
    print("Built ZIP and four preview scenarios in", dist)


if __name__ == "__main__":
    build()
