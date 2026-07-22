#!/usr/bin/env python3
import argparse
import html
import json
import math
import re
import shutil
import sys
import tomllib
from datetime import date, timedelta
from pathlib import Path

try:
    import markdown
except ImportError:
    sys.exit("build.py requires the 'markdown' package: pip install markdown")

ROOT = Path(__file__).resolve().parent

SET_TOKEN = re.compile(r"^(\d+)x(bw|\d+(?:[.,]\d+)?)$", re.IGNORECASE)
NOTE_NAME = re.compile(r"^(\d{4})-W(\d{2})$")

LIFT_ORDER = [
    "goblet_squat",
    "floor_press",
    "row",
    "rdl",
    "reverse_lunge",
    "ohp",
    "pullover",
    "chin_ups",
    "hip_thrust",
]
LIFT_NAMES = {
    "goblet_squat": "Goblet squat",
    "floor_press": "Floor press",
    "row": "One-arm row",
    "rdl": "RDL",
    "reverse_lunge": "Reverse lunge",
    "ohp": "Overhead press",
    "pullover": "Pullover",
    "chin_ups": "Chin-ups",
    "hip_thrust": "Hip thrust",
}

MONTHS = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]


def fail(msg):
    sys.exit(f"build.py: error: {msg}")


def esc(s):
    return html.escape(str(s), quote=True)


def lift_name(key):
    return LIFT_NAMES.get(key, key.replace("_", " ").capitalize())


def parse_sets(text, where):
    out = []
    for tok in str(text).split():
        tok = tok.strip(",;")
        if not tok:
            continue
        m = SET_TOKEN.match(tok)
        if not m:
            fail(
                f"{where}: bad set token '{tok}' (expected REPSxWEIGHT, e.g. '12x20' or '8xbw')"
            )
        w = None if m[2].lower() == "bw" else float(m[2].replace(",", "."))
        out.append((w, int(m[1])))
    return out


def fmt_kg(v):
    return f"{v:g}" if v == round(v, 1) else f"{v:.1f}"


def fmt_sets(sets):
    return " ".join(f"{r}×" + ("bw" if w is None else fmt_kg(w)) for w, r in sets)


def top_set(sets):
    weighted = [(w, r) for w, r in sets if w is not None]
    if weighted:
        return max(weighted, key=lambda s: (s[0], s[1]))
    return max(sets, key=lambda s: s[1]) if sets else None


def fmt_duration(seconds):
    m, s = divmod(round(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02}:{s:02}" if h else f"{m}:{s:02}"


def fmt_pace(sec_per_km):
    m, s = divmod(round(sec_per_km), 60)
    return f"{m}′{s:02}″/km"


def fmt_date(d):
    return f"{d.day} {d.strftime('%b')}"


def fmt_delta(v, decimals=1, unit=""):
    sign = "−" if v < 0 else "+"
    return f"{sign}{abs(v):.{decimals}f}{unit}"


def load_json(path, key):
    if not path.exists():
        return []
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))[key]
    except (json.JSONDecodeError, KeyError) as e:
        fail(f"{path}: {e}")
    for row in rows:
        row["date"] = date.fromisoformat(row["date"])
    return sorted(rows, key=lambda r: r["date"])


def load_config(data_dir):
    cfg = {"start": None, "goal": (77.0, 80.0)}
    path = data_dir / "config.toml"
    if path.exists():
        try:
            doc = tomllib.loads(path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as e:
            fail(f"{path}: {e}")
        if doc.get("start"):
            cfg["start"] = doc["start"]
        if doc.get("goal_kg"):
            cfg["goal"] = tuple(doc["goal_kg"])
    return cfg


def load_garmin(data_dir):
    g = data_dir / "garmin"
    return {
        "weights": load_json(g / "weight.json", "weigh_ins"),
        "runs": load_json(g / "runs.json", "runs"),
        "daily": load_json(g / "daily.json", "days"),
    }


def load_log(data_dir):
    strength, runs, measures = [], [], []
    for path in sorted((data_dir / "log").glob("*.toml")):
        try:
            doc = tomllib.loads(path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as e:
            fail(f"{path}: {e}")
        for entry in doc.get("strength", []):
            where = f"{path.name}: [[strength]] {entry.get('date', '?')}"
            if "date" not in entry:
                fail(f"{where}: missing date")
            lifts = {}
            for k, v in entry.items():
                if k in ("date", "session", "notes"):
                    continue
                lifts[k] = parse_sets(v, f"{where}: {k}")
            strength.append(
                {
                    "date": entry["date"],
                    "session": entry.get("session", ""),
                    "notes": entry.get("notes", ""),
                    "lifts": lifts,
                }
            )
        for entry in doc.get("run", []):
            if "date" not in entry:
                fail(f"{path.name}: [[run]] missing date")
            runs.append(entry)
        for entry in doc.get("measure", []):
            if "date" not in entry:
                fail(f"{path.name}: [[measure]] missing date")
            measures.append(entry)
    strength.sort(key=lambda e: e["date"])
    runs.sort(key=lambda e: e["date"])
    measures.sort(key=lambda e: e["date"])
    return strength, runs, measures


def load_notes(notes_dir):
    notes = []
    for path in notes_dir.glob("*.md"):
        m = NOTE_NAME.match(path.stem)
        if not m:
            print(f"  skipping note with unrecognized name: {path.name}")
            continue
        y, w = int(m[1]), int(m[2])
        notes.append(
            {
                "date": date.fromisocalendar(y, w, 1),
                "label": f"Week {w}, {y}",
                "html": markdown.markdown(
                    path.read_text(encoding="utf-8"), extensions=["tables"]
                ),
            }
        )
    notes.sort(key=lambda n: n["date"])
    return notes


def rolling_mean(points, days=7):
    out = []
    for d, _ in points:
        lo = d - timedelta(days=days - 1)
        win = [v for d2, v in points if lo <= d2 <= d]
        out.append((d, sum(win) / len(win)))
    return out


def week_monday(d):
    return d - timedelta(days=d.isoweekday() - 1)


def nice_step(span, target=4):
    if span <= 0:
        return 1.0
    raw = span / target
    mag = 10 ** math.floor(math.log10(raw))
    for s in (1, 2, 2.5, 5, 10):
        if raw / mag <= s:
            return s * mag
    return 10 * mag


def y_ticks(lo, hi, target=4):
    step = nice_step(hi - lo, target)
    t = math.ceil(lo / step - 1e-9) * step
    out = []
    while t <= hi + 1e-9:
        out.append(round(t, 10))
        t += step
    return out


def date_ticks(d0, d1):
    span = (d1 - d0).days
    if span <= 0:
        return [d0]
    if span <= 84:
        step = 7 if span <= 49 else 14
        first = week_monday(d0 + timedelta(days=6))
        ticks = []
        d = first
        while d <= d1:
            ticks.append(d)
            d += timedelta(days=step)
        return ticks or [d0]
    ticks = []
    d = date(d0.year, d0.month, 1)
    while d <= d1:
        if d >= d0:
            ticks.append(d)
        d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    if len(ticks) > 7:
        keep = max(1, round(len(ticks) / 6))
        ticks = ticks[::keep]
    return ticks or [d0]


def tick_label(d, span_days):
    return d.strftime("%b") if span_days > 84 else fmt_date(d)


class Plot:
    ml, mr, mt, mb = 46, 18, 10, 26

    def __init__(self, width, height, d0, d1, y0, y1):
        self.w, self.h = width, height
        self.d0, self.d1 = d0, d1
        self.y0, self.y1 = y0, y1
        self.pw = width - self.ml - self.mr
        self.ph = height - self.mt - self.mb

    def x(self, d):
        span = (self.d1 - self.d0).days or 1
        return self.ml + self.pw * (d - self.d0).days / span

    def y(self, v):
        span = (self.y1 - self.y0) or 1
        return self.mt + self.ph * (1 - (v - self.y0) / span)

    def frame(self, y_fmt=lambda v: f"{v:g}"):
        parts = []
        for t in y_ticks(self.y0, self.y1):
            yy = self.y(t)
            parts.append(
                f'<line class="grid" x1="{self.ml}" y1="{yy:.1f}" x2="{self.w - self.mr}" y2="{yy:.1f}"/>'
            )
            parts.append(
                f'<text class="ticklabel" x="{self.ml - 6}" y="{yy + 3.5:.1f}" text-anchor="end">{y_fmt(t)}</text>'
            )
        base = self.mt + self.ph
        parts.append(
            f'<line class="axis" x1="{self.ml}" y1="{base:.1f}" x2="{self.w - self.mr}" y2="{base:.1f}"/>'
        )
        span = (self.d1 - self.d0).days
        for d in date_ticks(self.d0, self.d1):
            xx = self.x(d)
            parts.append(
                f'<text class="ticklabel" x="{xx:.1f}" y="{base + 16:.1f}" text-anchor="middle">{tick_label(d, span)}</text>'
            )
        return "".join(parts)


def polyline(plot, points, cls):
    pts = " ".join(f"{plot.x(d):.1f},{plot.y(v):.1f}" for d, v in points)
    return f'<polyline class="{cls}" points="{pts}"/>'


def end_marker(plot, d, v, label, cls="dot-end"):
    x, y = plot.x(d), plot.y(v)
    anchor = "end" if x > plot.w - 70 else "start"
    lx = x - 9 if anchor == "end" else x + 9
    return (
        f'<circle class="dot-ring" cx="{x:.1f}" cy="{y:.1f}" r="6.5"/>'
        f'<circle class="{cls}" cx="{x:.1f}" cy="{y:.1f}" r="4.5"/>'
        f'<text class="endlabel" x="{lx:.1f}" y="{y - 8:.1f}" text-anchor="{anchor}">{esc(label)}</text>'
    )


def start_marker(p, start):
    if start is None or start <= p.d0 or start > p.d1:
        return ""
    x = p.x(start)
    flip = x > p.w - p.mr - 80
    lx = x - 4 if flip else x + 4
    anchor = "end" if flip else "start"
    return (
        f'<rect class="pre-band" x="{p.ml}" y="{p.mt}" width="{x - p.ml:.1f}" height="{p.ph}"/>'
        f'<line class="start-line" x1="{x:.1f}" y1="{p.mt}" x2="{x:.1f}" y2="{p.mt + p.ph}"/>'
        f'<text class="striplabel" x="{lx:.1f}" y="{p.mt + 11:.1f}" text-anchor="{anchor}">program start</text>'
    )


def bar_path(x, y, w, h, r=4):
    r = max(0.0, min(r, w / 2, h))
    return (
        f"M{x:.1f},{y + h:.1f} L{x:.1f},{y + r:.1f} Q{x:.1f},{y:.1f} {x + r:.1f},{y:.1f} "
        f"L{x + w - r:.1f},{y:.1f} Q{x + w:.1f},{y:.1f} {x + w:.1f},{y + r:.1f} L{x + w:.1f},{y + h:.1f} Z"
    )


def svg(width, height, body):
    return (
        f'<svg viewBox="0 0 {width} {height}" role="img" '
        f'preserveAspectRatio="xMidYMid meet">{body}</svg>'
    )


def chart_figure(title, inner, table_rows, table_head, empty=False):
    if empty:
        inner = '<div class="chart-empty">no data yet</div>'
    table = ""
    if table_rows:
        head = "".join(f"<th>{esc(h)}</th>" for h in table_head)
        body = "".join(
            "<tr>" + "".join(f'<td class="num">{esc(c)}</td>' for c in row) + "</tr>"
            for row in table_rows
        )
        table = (
            f"<details><summary>data</summary><table>"
            f"<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></details>"
        )
    return f'<figure class="chart"><h3>{esc(title)}</h3>{inner}{table}</figure>'


def weight_chart(weights, config):
    goal_lo, goal_hi = config["goal"]
    points = [(r["date"], r["kg"]) for r in weights]
    rows = [(fmt_date(d), f"{v:.1f}") for d, v in reversed(points)]
    if len(points) < 2:
        return chart_figure("Weight (kg)", "", rows, ("date", "kg"), empty=True)
    trend = rolling_mean(points, 28)
    vals = [v for _, v in points]
    y0 = min(min(vals), goal_lo) - 0.8
    y1 = max(vals) + 0.8
    W, H = 720, 300
    p = Plot(W, H, points[0][0], points[-1][0], y0, y1)
    body = [p.frame(lambda v: f"{v:g}"), start_marker(p, config["start"])]
    band_top = p.y(min(goal_hi, p.y1))
    band_bot = p.y(max(goal_lo, p.y0))
    body.append(
        f'<rect class="goal-band" x="{p.ml}" y="{band_top:.1f}" '
        f'width="{p.pw}" height="{band_bot - band_top:.1f}"/>'
    )
    body.append(
        f'<text class="bandlabel" x="{p.w - p.mr - 6}" y="{band_top + 14:.1f}" '
        f'text-anchor="end">goal {goal_lo:g}–{goal_hi:g}</text>'
    )
    for d, v in points:
        body.append(
            f'<circle class="dot-raw" cx="{p.x(d):.1f}" cy="{p.y(v):.1f}" r="2.5">'
            f"<title>{fmt_date(d)}: {v:.1f} kg</title></circle>"
        )
    body.append(polyline(p, trend, "line-data"))
    td, tv = trend[-1]
    body.append(end_marker(p, td, tv, f"{tv:.1f}"))
    return chart_figure(
        "Weight (kg) — all weigh-ins, 28-day trend",
        svg(W, H, "".join(body)),
        rows,
        ("date", "kg"),
    )


def running_chart(garmin_runs, manual_runs, config):
    knee_by_date = {
        r["date"]: r.get("knee") for r in manual_runs if r.get("knee") is not None
    }
    run_dates = sorted({r["date"] for r in garmin_runs} | set(knee_by_date))
    weeks = {}
    for r in garmin_runs:
        weeks.setdefault(week_monday(r["date"]), 0.0)
        weeks[week_monday(r["date"])] += r["duration_s"] / 60.0
    for d in knee_by_date:
        weeks.setdefault(week_monday(d), 0.0)
    rows = [
        (fmt_date(wk), f"{mins:.0f}")
        for wk, mins in sorted(weeks.items(), reverse=True)
    ]
    if not weeks or len(run_dates) < 2:
        return chart_figure(
            "Running — weekly minutes, knee response",
            "",
            rows,
            ("week of", "min"),
            empty=True,
        )
    d0 = week_monday(min(run_dates))
    d1 = week_monday(max(run_dates)) + timedelta(days=6)
    max_min = max(weeks.values())
    W, strip_h, gap = 720, 76, 14
    H = 308
    p = Plot(W, H, d0, d1, 0, max(max_min * 1.15, 10))
    p.mt = strip_h + gap + 10
    p.ph = H - p.mt - p.mb
    body = [p.frame(lambda v: f"{v:g}"), start_marker(p, config["start"])]
    week_px = p.pw * 7 / max(1, (d1 - d0).days)
    bw = min(24.0, week_px * 0.55)
    latest_wk = max(weeks)
    for wk, mins in sorted(weeks.items()):
        cx = (p.x(wk) + p.x(wk + timedelta(days=6))) / 2
        y = p.y(mins)
        h = p.mt + p.ph - y
        if h > 0.5:
            body.append(
                f'<path class="bar" d="{bar_path(cx - bw / 2, y, bw, h)}">'
                f"<title>week of {fmt_date(wk)}: {mins:.0f} min</title></path>"
            )
        if wk == latest_wk and mins > 0:
            body.append(
                f'<text class="endlabel" x="{cx:.1f}" y="{y - 6:.1f}" '
                f'text-anchor="middle">{mins:.0f} min</text>'
            )
    strip_top = 10
    level_y = lambda score: strip_top + (3 - score) * ((strip_h - 20) / 3) + 6
    for score in (0, 1, 2, 3):
        yy = level_y(score)
        body.append(
            f'<text class="ticklabel" x="{p.ml - 6}" y="{yy + 3.5:.1f}" text-anchor="end">{score}</text>'
        )
    body.append(
        f'<text class="striplabel" x="{p.ml}" y="{strip_top - 1}">knee score, morning after (0 = silent, 3 = bad)</text>'
    )
    for d in run_dates:
        score = knee_by_date.get(d)
        if score is None:
            continue
        x, y = p.x(d), level_y(score)
        body.append(
            f'<circle class="dot-ring" cx="{x:.1f}" cy="{y:.1f}" r="6.5"/>'
            f'<circle class="knee k{score}" cx="{x:.1f}" cy="{y:.1f}" r="4.5">'
            f"<title>{fmt_date(d)}: knee {score}</title></circle>"
        )
    return chart_figure(
        "Running — weekly minutes, knee response",
        svg(W, H, "".join(body)),
        rows,
        ("week of", "min"),
    )


def lift_charts(strength):
    series = {}
    order = []
    for entry in strength:
        for key, sets in entry["lifts"].items():
            ts = top_set(sets)
            if ts is None:
                continue
            if key not in series:
                series[key] = []
                order.append(key)
            series[key].append((entry["date"], ts))
    order.sort(key=lambda k: (LIFT_ORDER.index(k) if k in LIFT_ORDER else 99, k))
    if not order:
        return chart_figure("Lifts — top set per session", "", [], (), empty=True)
    panels = []
    for key in order:
        pts = series[key]
        bodyweight = all(w is None for _, (w, _) in pts)
        vals = [(d, (r if bodyweight else w)) for d, (w, r) in pts]
        unit = "reps" if bodyweight else "kg"
        rows = [(fmt_date(d), fmt_sets([ts])) for d, ts in reversed(pts)]
        W, H = 340, 170
        if len(vals) < 2:
            last = vals[-1][1] if vals else None
            inner = (
                f'<div class="chart-empty">{fmt_kg(last) if last is not None else "no data"}'
                f"{' ' + unit if last is not None else ''} — need 2+ sessions to chart</div>"
            )
            panels.append(
                chart_figure(lift_name(key), inner, rows, ("date", "top set"))
            )
            continue
        vv = [v for _, v in vals]
        pad = max((max(vv) - min(vv)) * 0.15, 1.0)
        p = Plot(W, H, vals[0][0], vals[-1][0], min(vv) - pad, max(vv) + pad)
        body = [p.frame(lambda v: f"{v:g}")]
        body.append(polyline(p, vals, "line-data"))
        for d, v in vals[:-1]:
            body.append(
                f'<circle class="dot-mid" cx="{p.x(d):.1f}" cy="{p.y(v):.1f}" r="3">'
                f"<title>{fmt_date(d)}: {fmt_kg(v)} {unit}</title></circle>"
            )
        d, v = vals[-1]
        w, r = pts[-1][1]
        label = f"{r} reps" if bodyweight else f"{r}×{fmt_kg(w)} kg"
        body.append(end_marker(p, d, v, label))
        panels.append(
            chart_figure(
                lift_name(key), svg(W, H, "".join(body)), rows, ("date", "top set")
            )
        )
    return '<div class="multiples">' + "".join(panels) + "</div>"


def simple_line_chart(
    title, points, unit, y_fmt=lambda v: f"{v:g}", decimals=1, trend=False, start=None
):
    rows = [(fmt_date(d), f"{v:.{decimals}f}") for d, v in reversed(points)]
    if len(points) < 2:
        return chart_figure(title, "", rows, ("date", unit), empty=True)
    vv = [v for _, v in points]
    pad = max((max(vv) - min(vv)) * 0.15, 1.0)
    W, H = 720, 200
    p = Plot(W, H, points[0][0], points[-1][0], min(vv) - pad, max(vv) + pad)
    body = [p.frame(y_fmt), start_marker(p, start)]
    if trend:
        smoothed = rolling_mean(points)
        for d, v in points:
            body.append(
                f'<circle class="dot-raw" cx="{p.x(d):.1f}" cy="{p.y(v):.1f}" r="2.5">'
                f"<title>{fmt_date(d)}: {v:.{decimals}f} {unit}</title></circle>"
            )
        body.append(polyline(p, smoothed, "line-data"))
        d, v = smoothed[-1]
    else:
        body.append(polyline(p, points, "line-data"))
        for d, v in points[:-1]:
            body.append(
                f'<circle class="dot-mid" cx="{p.x(d):.1f}" cy="{p.y(v):.1f}" r="3">'
                f"<title>{fmt_date(d)}: {v:.{decimals}f} {unit}</title></circle>"
            )
        d, v = points[-1]
    body.append(end_marker(p, d, v, f"{v:.{decimals}f}"))
    return chart_figure(title, svg(W, H, "".join(body)), rows, ("date", unit))


def tile(label, value, delta_html="", hero=False):
    cls = "tile tile-hero" if hero else "tile"
    return (
        f'<div class="{cls}"><div class="label">{esc(label)}</div>'
        f'<div class="value">{value}</div>{delta_html}</div>'
    )


def delta_span(v, good_when_down, decimals=1, unit="", vs="vs last week"):
    if v is None or round(abs(v), decimals) == 0:
        return ""
    good = (v < 0) == good_when_down or v == 0
    cls = "delta-good" if good else "delta-bad"
    return f'<div class="delta {cls}">{fmt_delta(v, decimals, unit)} <span class="vs">{esc(vs)}</span></div>'


def build_tiles(garmin, strength, manual_runs, measures):
    tiles = []
    weights = [(r["date"], r["kg"]) for r in garmin["weights"]]
    if weights:
        trend = rolling_mean(weights, 28)
        cur_d, cur_v = trend[-1]
        base = [(d, v) for d, v in trend if d <= cur_d - timedelta(days=28)]
        bd, bv = base[-1] if base else trend[0]
        span = (cur_d - bd).days
        rate = (cur_v - bv) / span * 7 if span >= 14 else None
        tiles.append(
            tile(
                "Weight, 28-day trend",
                f'{cur_v:.1f}<span class="unit">kg</span>',
                delta_span(
                    rate,
                    good_when_down=True,
                    decimals=2,
                    unit=" kg/wk",
                    vs=f"rate, last {span} days",
                ),
                hero=True,
            )
        )
    else:
        tiles.append(tile("Weight, 28-day trend", "—", hero=True))
    if measures:
        waists = [(m["date"], m["waist"]) for m in measures if "waist" in m]
        if waists:
            delta = (waists[-1][1] - waists[-2][1]) if len(waists) > 1 else None
            tiles.append(
                tile(
                    "Waist",
                    f'{waists[-1][1]:g}<span class="unit">cm</span>',
                    delta_span(
                        delta, good_when_down=True, unit=" cm", vs="vs previous"
                    ),
                )
            )
    daily = garmin["daily"]
    rhr = [(r["date"], r["resting_hr"]) for r in daily if r.get("resting_hr")]
    if rhr:
        last7 = [v for d, v in rhr if d > rhr[-1][0] - timedelta(days=7)]
        prev7 = [
            v
            for d, v in rhr
            if rhr[-1][0] - timedelta(days=14) < d <= rhr[-1][0] - timedelta(days=7)
        ]
        cur = sum(last7) / len(last7)
        delta = (cur - sum(prev7) / len(prev7)) if prev7 else None
        tiles.append(
            tile(
                "Resting HR, 7-day",
                f'{cur:.0f}<span class="unit">bpm</span>',
                delta_span(delta, good_when_down=True, decimals=0, unit=" bpm"),
            )
        )
    steps = [(r["date"], r["steps"]) for r in daily if r.get("steps")]
    if steps:
        last7 = [v for d, v in steps if d > steps[-1][0] - timedelta(days=7)]
        cur = sum(last7) / len(last7)
        tiles.append(
            tile("Steps, 7-day avg", f'{cur / 1000:.1f}<span class="unit">k</span>')
        )
    rungs = [r["rung"] for r in manual_runs if "rung" in r]
    if rungs:
        tiles.append(tile("Ladder rung", f'{rungs[-1]}<span class="unit">/ 8</span>'))
    this_wk = week_monday(date.today())
    mins = sum(
        r["duration_s"] / 60
        for r in garmin["runs"]
        if week_monday(r["date"]) == this_wk
    )
    prev = sum(
        r["duration_s"] / 60
        for r in garmin["runs"]
        if week_monday(r["date"]) == this_wk - timedelta(days=7)
    )
    if garmin["runs"]:
        tiles.append(
            tile(
                "Run minutes this week",
                f'{mins:.0f}<span class="unit">min</span>',
                delta_span(
                    mins - prev if prev else None,
                    good_when_down=False,
                    decimals=0,
                    unit=" min",
                ),
            )
        )
    return '<div class="tiles">' + "".join(tiles) + "</div>"


def page(title, body, depth, generated):
    up = "../" * depth
    nav = (
        f'<nav><a class="brand" href="{up if depth else "./"}">marzer / <strong>fitness</strong></a>'
        f'<a href="{up}log/">log</a><a href="{up}program/">program</a>'
        f'<a class="ext" href="/">blog</a></nav>'
    )
    return (
        f'<!DOCTYPE html>\n<html lang="en"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<meta name="color-scheme" content="light dark">'
        f"<title>{esc(title)}</title>"
        f'<link rel="stylesheet" href="{up}fitness.css">'
        f'<link rel="icon" href="/favicon-light.png"></head>'
        f"<body><header>{nav}</header><main>{body}</main>"
        f"<footer>generated {generated} · "
        f'<a href="https://github.com/marzer/marzer.github.io/tree/main/fitness">data &amp; source</a>'
        f"</footer></body></html>\n"
    )


def program_line(config):
    s = config["start"]
    if not s:
        return ""
    today = date.today()
    if today < s:
        return f'<p class="legend">program starts {fmt_date(s)} {s.year}</p>'
    wk = (today - s).days // 7 + 1
    return f'<p class="legend">program week {wk} · started {fmt_date(s)} {s.year}</p>'


def render_dashboard(garmin, strength, manual_runs, measures, notes, config):
    parts = ["<h1>fitness</h1>", program_line(config)]
    parts.append(build_tiles(garmin, strength, manual_runs, measures))
    parts.append(weight_chart(garmin["weights"], config))
    parts.append(running_chart(garmin["runs"], manual_runs, config))
    parts.append("<h2>Lifts — top set per session</h2>")
    parts.append(lift_charts(strength))
    waists = [(m["date"], m["waist"]) for m in measures if "waist" in m]
    parts.append(simple_line_chart("Waist (cm)", waists, "cm", start=config["start"]))
    rhr = [
        (r["date"], float(r["resting_hr"]))
        for r in garmin["daily"]
        if r.get("resting_hr")
    ]
    parts.append(
        simple_line_chart(
            "Resting HR (bpm) — 7-day trend",
            rhr,
            "bpm",
            decimals=0,
            trend=True,
            start=config["start"],
        )
    )
    if notes:
        latest = notes[-1]
        parts.append(
            f"<h2>Latest note — {esc(latest['label'])}</h2>"
            f'<div class="note">{latest["html"]}</div>'
            f'<p><a href="log/">full log →</a></p>'
        )
    return "".join(parts)


def render_log(garmin, strength, manual_runs, measures, notes):
    manual_by_date = {r["date"]: r for r in manual_runs}
    garmin_by_date = {r["date"]: r for r in garmin["runs"]}
    all_run_dates = sorted(set(manual_by_date) | set(garmin_by_date), reverse=True)
    months = sorted(
        {
            (d.year, d.month)
            for d in (
                [e["date"] for e in strength]
                + all_run_dates
                + [m["date"] for m in measures]
                + [n["date"] for n in notes]
            )
        },
        reverse=True,
    )
    if not months:
        return '<h1>log</h1><p class="chart-empty">nothing logged yet</p>'
    parts = [
        "<h1>log</h1>",
        '<p class="legend">knee = next-morning self-assessment, '
        '0 (silent) → 3 (bad) — full scale in the <a href="../program/">program</a></p>',
    ]
    for y, mo in months:
        in_month = lambda d: d.year == y and d.month == mo
        parts.append(f"<h2>{MONTHS[mo - 1]} {y}</h2>")
        month_notes = [n for n in notes if in_month(n["date"])]
        for n in reversed(month_notes):
            parts.append(
                f'<h3>{esc(n["label"])}</h3><div class="note">{n["html"]}</div>'
            )
        month_runs = [d for d in all_run_dates if in_month(d)]
        if month_runs:
            rows = []
            for d in month_runs:
                g = garmin_by_date.get(d, {})
                m = manual_by_date.get(d, {})
                pace = (
                    fmt_pace(g["duration_s"] / (g["distance_m"] / 1000))
                    if g.get("distance_m")
                    else "—"
                )
                dur = fmt_duration(g["duration_s"]) if g.get("duration_s") else "—"
                km = f"{g['distance_m'] / 1000:.1f}" if g.get("distance_m") else "—"
                rows.append(
                    "<tr>"
                    f"<td>{fmt_date(d)}</td>"
                    f'<td class="num">{m.get("rung", "—")}</td>'
                    f'<td class="num">{dur}</td>'
                    f'<td class="num">{km}</td>'
                    f'<td class="num">{pace}</td>'
                    f'<td class="num">{g.get("avg_hr", "—")}</td>'
                    f'<td class="num">{g.get("avg_cadence", "—")}</td>'
                    f'<td class="num">{m.get("knee", "—")}</td>'
                    "</tr>"
                )
            parts.append(
                "<h3>Runs</h3><table><thead><tr><th>date</th><th>rung</th><th>time</th>"
                "<th>km</th><th>pace</th><th>HR</th><th>cad</th>"
                '<th title="next-morning knee score: 0 silent, 3 altered gait">knee</th>'
                "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
            )
        month_strength = [e for e in strength if in_month(e["date"])]
        if month_strength:
            rows = []
            for e in reversed(month_strength):
                lifts = "<br>".join(
                    f"{esc(lift_name(k))}: {esc(fmt_sets(s))}"
                    for k, s in e["lifts"].items()
                )
                note = (
                    f'<div class="cell-note">{esc(e["notes"])}</div>'
                    if e["notes"]
                    else ""
                )
                rows.append(
                    f"<tr><td>{fmt_date(e['date'])}</td>"
                    f'<td class="num">{esc(e["session"])}</td><td>{lifts}{note}</td></tr>'
                )
            parts.append(
                "<h3>Strength</h3><table><thead><tr><th>date</th><th>session</th>"
                "<th>sets</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
            )
        month_measures = [m for m in measures if in_month(m["date"])]
        if month_measures:
            rows = []
            for m in reversed(month_measures):
                vals = " · ".join(f"{k} {v:g}" for k, v in m.items() if k != "date")
                rows.append(
                    f'<tr><td>{fmt_date(m["date"])}</td><td class="num">{esc(vals)}</td></tr>'
                )
            parts.append(
                "<h3>Measurements</h3><table><tbody>"
                + "".join(rows)
                + "</tbody></table>"
            )
    return "".join(parts)


def render_program(program_path):
    text = program_path.read_text(encoding="utf-8")
    return (
        '<div class="prose">'
        + markdown.markdown(text, extensions=["tables"])
        + "</div>"
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT.parent / "html" / "fitness")
    ap.add_argument("--src", type=Path, default=ROOT)
    args = ap.parse_args()

    src = args.src.resolve()
    config = load_config(src / "data")
    garmin = load_garmin(src / "data")
    strength, manual_runs, measures = load_log(src / "data")
    notes = load_notes(src / "notes")
    generated = date.today().isoformat()

    out = args.out.resolve()
    if out.exists():
        shutil.rmtree(out)
    (out / "log").mkdir(parents=True)
    (out / "program").mkdir()

    (out / "index.html").write_text(
        page(
            "fitness — marzer",
            render_dashboard(garmin, strength, manual_runs, measures, notes, config),
            0,
            generated,
        ),
        encoding="utf-8",
        newline="\n",
    )
    (out / "log" / "index.html").write_text(
        page(
            "log — fitness — marzer",
            render_log(garmin, strength, manual_runs, measures, notes),
            1,
            generated,
        ),
        encoding="utf-8",
        newline="\n",
    )
    (out / "program" / "index.html").write_text(
        page(
            "program — fitness — marzer",
            render_program(src / "program.md"),
            1,
            generated,
        ),
        encoding="utf-8",
        newline="\n",
    )
    shutil.copy2(src / "static" / "fitness.css", out / "fitness.css")

    counts = (
        f"{len(garmin['weights'])} weigh-ins, {len(garmin['runs'])} runs, "
        f"{len(strength)} strength sessions, {len(notes)} notes"
    )
    print(f"fitness site → {out} ({counts})")


if __name__ == "__main__":
    main()
