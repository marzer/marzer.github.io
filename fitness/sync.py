#!/usr/bin/env python3
import argparse
import getpass
import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path

try:
    from garminconnect import Garmin
except ImportError:
    sys.exit("sync.py requires: pip install garminconnect curl_cffi")

ROOT = Path(__file__).resolve().parent
GARMIN_DIR = ROOT / "data" / "garmin"
TOKENSTORE = "~/.garminconnect"
BACKFILL_DAYS = 62
FILES = (("weight.json", "weigh_ins"), ("runs.json", "runs"), ("daily.json", "days"))


def read_rows(name, key):
    path = GARMIN_DIR / name
    if not path.exists():
        return {}
    return {r["date"]: r for r in json.loads(path.read_text(encoding="utf-8"))[key]}


def write_rows(name, key, rows):
    path = GARMIN_DIR / name
    payload = {key: [rows[d] for d in sorted(rows)]}
    path.write_text(
        json.dumps(payload, indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def default_since():
    dates = [d for name, key in FILES for d in read_rows(name, key)]
    if dates:
        return date.fromisoformat(max(dates)) - timedelta(days=3)
    return date.today() - timedelta(days=BACKFILL_DAYS)


def daterange(since, until):
    d = since
    while d <= until:
        yield d
        d += timedelta(days=1)


def login():
    g = Garmin()
    try:
        g.login(TOKENSTORE)
        return g
    except Exception:
        pass
    print("no cached Garmin session; logging in (tokens cache to ~/.garminconnect)")
    email = input("garmin email: ").strip()
    password = getpass.getpass("garmin password: ")
    g = Garmin(
        email=email, password=password, prompt_mfa=lambda: input("MFA code: ").strip()
    )
    g.login(TOKENSTORE)
    return g


def sync_weight(g, since, until):
    rows = read_rows("weight.json", "weigh_ins")
    n = 0
    data = g.get_body_composition(since.isoformat(), until.isoformat())
    for e in data.get("dateWeightList", []):
        d, w = e.get("calendarDate"), e.get("weight")
        if not d or not w:
            continue
        row = {"date": d, "kg": round(w / 1000, 1)}
        if e.get("bodyFat"):
            row["fat_pct"] = round(e["bodyFat"], 1)
        if rows.get(d) != row:
            rows[d] = row
            n += 1
    write_rows("weight.json", "weigh_ins", rows)
    return n


def sync_runs(g, since, until):
    rows = read_rows("runs.json", "runs")
    n = 0
    for a in g.get_activities_by_date(since.isoformat(), until.isoformat(), "running"):
        type_key = (a.get("activityType") or {}).get("typeKey", "")
        if "running" not in type_key:
            continue
        d = str(a.get("startTimeLocal", ""))[:10]
        dur = a.get("duration")
        if not d or not dur:
            continue
        row = {"date": d, "duration_s": round(dur)}
        if a.get("distance"):
            row["distance_m"] = round(a["distance"])
        if a.get("averageHR"):
            row["avg_hr"] = round(a["averageHR"])
        if a.get("averageRunningCadenceInStepsPerMinute"):
            row["avg_cadence"] = round(a["averageRunningCadenceInStepsPerMinute"])
        old = rows.get(d)
        if old and old.get("duration_s", 0) > row["duration_s"]:
            continue
        if old != row:
            rows[d] = row
            n += 1
    write_rows("runs.json", "runs", rows)
    return n


def sync_daily(g, since, until):
    rows = read_rows("daily.json", "days")
    n = 0
    for e in g.get_daily_steps(since.isoformat(), until.isoformat()):
        d = e.get("calendarDate")
        if not d or not e.get("totalSteps"):
            continue
        row = rows.get(d, {"date": d})
        if row.get("steps") != e["totalSteps"]:
            row["steps"] = e["totalSteps"]
            rows[d] = row
            n += 1
    missing = [
        d
        for d in daterange(since, until)
        if "resting_hr" not in rows.get(d.isoformat(), {})
    ]
    for i, d in enumerate(missing):
        if i and i % 10 == 0:
            print(f"  resting HR: {i}/{len(missing)} days...")
        data = g.get_rhr_day(d.isoformat())
        metrics = ((data or {}).get("allMetrics") or {}).get("metricsMap") or {}
        for m in metrics.get("WELLNESS_RESTING_HEART_RATE") or []:
            cd, val = m.get("calendarDate"), m.get("value")
            if not cd or not val:
                continue
            row = rows.get(cd, {"date": cd})
            if row.get("resting_hr") != round(val):
                row["resting_hr"] = round(val)
                rows[cd] = row
                n += 1
        time.sleep(0.3)
    write_rows("daily.json", "days", rows)
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", type=date.fromisoformat, default=None)
    ap.add_argument("--until", type=date.fromisoformat, default=date.today())
    args = ap.parse_args()
    since = args.since or default_since()
    if since > args.until:
        sys.exit(f"sync.py: --since {since} is after --until {args.until}")

    print(
        f"syncing {since} → {args.until} (summary metrics only; GPS/location is never fetched)"
    )
    g = login()
    print(f"  weight:     {sync_weight(g, since, args.until):+d} rows")
    print(f"  runs:       {sync_runs(g, since, args.until):+d} rows")
    print(f"  daily:      {sync_daily(g, since, args.until):+d} rows")
    print(f"done → review with: git diff fitness/data/garmin/")


if __name__ == "__main__":
    main()
