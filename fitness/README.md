# fitness

Source for [marzer.github.io/fitness](https://marzer.github.io/fitness/) — a
static fitness tracker. `build.py` renders everything in `data/` and
`notes/` to `html/fitness/`; CI runs it after poxy and deploys the lot.

Everything renders server-side; a small dependency-free script (`fitness.js`)
layers on chart tooltips, a theme toggle, and time-range toggles. With JS
disabled the site still works in full — controls simply don't appear.

Styling piggybacks on the parent site: every page `<link>`s the blog's
`/poxy/poxy.css` ahead of `fitness.css`, so it inherits the same fonts and
m.css theme variables for free. `fitness.css` maps those variables onto this
layout and adds one small reset (m.css makes `<body>` a flex column for its
sticky footer; here it flows normally). Light/dark is shared too — the toggle
here and on the blog both flip the same `poxy-theme-*` class and
`localStorage` key, so switching one switches both. This means the fitness
pages depend on poxy having run; they aren't styled standalone.

## Layout

```
fitness/
├── build.py          renders the site (stdlib + `markdown`)
├── sync.py           pulls Garmin data into data/garmin/ (run locally only)
├── program.md        the training program, rendered at /fitness/program/
├── static/           stylesheet + enhancement script
├── data/
│   ├── config.toml   program start date + goal weight band
│   ├── garmin/       machine-written JSON (sync.py); summary metrics only, never GPS
│   └── log/          hand-written TOML, one file per month
└── notes/            weekly commentary, markdown, named YYYY-Wnn.md
```

## Logging (phone-friendly, via GitHub web editor or anything else)

Everything manual goes in `data/log/YYYY-MM.toml`:

```toml
[[strength]]
date = 2026-07-21
session = "A"
goblet_squat = "12x20 11x20 10x20"
floor_press  = "12x18 12x18 10x18"
row          = "12x22 12x22 11x22"
rdl          = "12x24 12x24 12x24"

[[run]]
date = 2026-07-23
knee = 1

[[measure]]
date = 2026-07-26
waist = 104.0
```

Set strings are `REPSxWEIGHT` separated by spaces — said out loud: "12 reps of
20 kg" = `12x20`. `bw` for bodyweight (`chin_ups = "6xbw 5xbw"`); decimal weights
take a period or a comma (`10x22.5`, `10x22,5`). Any key in
`[[strength]]` other than `date`/`session`/`notes` is treated as an exercise.
Known exercise keys (others work too, these just get pretty names):
`goblet_squat` `floor_press` `row` `rdl` `reverse_lunge` `ohp` `pullover`
`chin_ups` `hip_thrust`.

`[[run]]` carries the one thing Garmin can't know: the next-morning `knee`
score (0–3). It joins the synced Garmin activity by date.

Weekly notes are plain markdown at `notes/2026-W30.md` (ISO week).

## Garmin data

`sync.py` logs into Garmin Connect via
[`garminconnect`](https://github.com/cyberjunky/python-garminconnect)
(`pip install garminconnect curl_cffi`) and merges summaries into
`data/garmin/`. It runs locally only — credentials and tokens never enter CI;
the site always builds from committed JSON.

```sh
fitness/sync.py                     # incremental; first run backfills ~2 months
fitness/sync.py --since 2026-05-01  # explicit range start
```

First run prompts for Garmin credentials (+ MFA code if enabled); tokens cache
to `~/.garminconnect` and survive ~a year, so subsequent runs are prompt-free.
Weigh-ins and steps come down in ranged calls; resting HR is fetched per
missing day, so the backfill takes a minute or two. Only whitelisted summary
fields are ever written — no GPS, no routes. Review before committing:
`git diff fitness/data/garmin/`. Schemas:

```json
weight.json  {"weigh_ins": [{"date": "2026-07-19", "kg": 84.5}]}
runs.json    {"runs": [{"date": "2026-07-23", "distance_m": 3100,
                        "duration_s": 1520, "avg_hr": 141, "avg_cadence": 172}]}
daily.json   {"days": [{"date": "2026-07-19", "resting_hr": 52, "steps": 8600}]}
```

Extra fields are allowed and ignored. Dates are ISO, lists sorted ascending.

## Building

```sh
poxy                          # main site → html/  (deletes html/ first!)
fitness/build.py              # fitness site → html/fitness/
python3 -m http.server -d html
```

Order matters: poxy wipes `html/`, and the fitness pages load the `poxy.css`
it emits (so styling only looks right once poxy has run). `build.py` needs
Python ≥ 3.11 and `pip install markdown`. A bad TOML entry or set string fails
the build with a message naming the file — fix and push again.
