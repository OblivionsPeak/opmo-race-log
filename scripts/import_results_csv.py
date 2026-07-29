"""
Build data/races.json from iRacing's exported result CSVs — no API, no auth.

iRacing removed legacy API auth in December 2025, and OAuth client IDs are
issued only by request (creation is currently paused), so the results export is
the reliable way in. On the iRacing results page for a race, use the export
button; you get eventresult_<subsessionid>_0.csv.

    python scripts/import_results_csv.py --list  path/to/eventresult_*.csv
    python scripts/import_results_csv.py --season "2026 Season 2" path/to/*.csv

Which entry is ours comes from scripts/team.json (cust_ids preferred, team-name
substrings as fallback) — same config the API puller uses.

Re-importing the same race updates it in place and preserves any hand-edited
livery_image / season / event / notes.
"""
import argparse
import csv
import glob
import io
import json
import pathlib
import re
import sys

# Driver names are full Unicode and the Windows console defaults to cp1252,
# which raises UnicodeEncodeError mid-print. Never let a name kill an import.
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except (AttributeError, ValueError):
    pass

ROOT = pathlib.Path(__file__).resolve().parent.parent
RACES_JSON = ROOT / 'data' / 'races.json'
TEAM_JSON = pathlib.Path(__file__).resolve().parent / 'team.json'

PRESERVE = ('livery_image', 'season', 'event', 'notes')


def load_team_config() -> dict:
    if TEAM_JSON.is_file():
        return json.loads(TEAM_JSON.read_text(encoding='utf-8'))
    return {'team_names': [], 'cust_ids': []}


def parse_csv(path: pathlib.Path):
    """Return (event_info, [result_row_dicts]). The export is two stacked tables."""
    rows = list(csv.reader(io.open(path, encoding='utf-8-sig', newline='')))

    event = {}
    if rows and rows[0] and rows[0][0].strip() == 'Start Time' and len(rows) > 1:
        event = dict(zip(rows[0], rows[1]))

    # the results table starts at its own header row
    start = next((i for i, r in enumerate(rows) if r and r[0].strip() == 'Fin Pos'), None)
    if start is None:
        return event, []

    header = [h.strip() for h in rows[start]]
    results = []
    for r in rows[start + 1:]:
        if not r or not r[0].strip():
            continue
        results.append(dict(zip(header, r)))
    return event, results


def as_int(val, default=None):
    try:
        return int(str(val).strip())
    except (TypeError, ValueError):
        return default


def group_entries(results):
    """
    Group result rows into entries.

    Team events export one row for the team (Cust ID == Team ID, both negative)
    followed by one row per driver sharing that Team ID. Solo events have no
    team rows at all, so each row is its own entry.
    """
    entries = []
    by_team = {}

    for row in results:
        team_id = as_int(row.get('Team ID'), 0)
        cust_id = as_int(row.get('Cust ID'), 0)

        if not team_id:                                   # solo entry
            entries.append({'summary': row, 'drivers': [row]})
            continue

        entry = by_team.get(team_id)
        if entry is None:
            entry = {'summary': None, 'drivers': []}
            by_team[team_id] = entry
            entries.append(entry)

        if cust_id == team_id:                            # the team's own row
            entry['summary'] = row
        else:
            entry['drivers'].append(row)

    # a team whose summary row is missing still needs one to read positions from
    for e in entries:
        if e['summary'] is None and e['drivers']:
            e['summary'] = e['drivers'][0]
    return [e for e in entries if e['summary']]


def entry_label(entry):
    return (entry['summary'].get('Name') or '').strip()


def find_our_entry(entries, cfg):
    ids = {int(c) for c in cfg.get('cust_ids', []) if str(c).strip().isdigit()}
    names = [n.lower() for n in cfg.get('team_names', []) if n]

    for e in entries:
        drv_ids = {as_int(d.get('Cust ID'), 0) for d in e['drivers']}
        drv_ids.add(as_int(e['summary'].get('Cust ID'), 0))
        if ids & drv_ids:
            return e
    for e in entries:
        label = entry_label(e).lower()
        if names and any(n in label for n in names):
            return e
    return None


def derive_length(*texts):
    """'24 Hours of Nurburgring' -> '24h'. Falls back to nothing."""
    for t in texts:
        if not t:
            continue
        m = re.search(r'(\d+)\s*(?:hours?|hr)\b', t, re.I)
        if m:
            return f'{m.group(1)}h'
        m = re.search(r'(\d+)\s*(?:minutes?|mins?)\b', t, re.I)
        if m:
            return f'{m.group(1)} min'
    return ''


def subsession_from_name(path: pathlib.Path):
    m = re.search(r'(\d{5,})', path.stem)
    return int(m.group(1)) if m else None


def build_record(path, cfg, want_list=False):
    event, results = parse_csv(path)
    if not results:
        print(f'  ! {path.name}: no result rows found — is this an iRacing export?')
        return None

    entries = group_entries(results)

    if want_list:
        print(f'\n{path.name} — {len(entries)} entries:')
        for e in sorted(entries, key=lambda x: as_int(x['summary'].get('Fin Pos'), 999)):
            names = ', '.join((d.get('Name') or '').strip() for d in e['drivers']) or '—'
            print(f"  P{e['summary'].get('Fin Pos','?'):<4} {entry_label(e):<38} "
                  f"team_id={e['summary'].get('Team ID','-'):<9} {names}")
        return None

    entry = find_our_entry(entries, cfg)
    if entry is None:
        print(f'  ! {path.name}: no OpMo entry matched. Run with --list and fill in '
              f'scripts/team.json')
        return None

    s = entry['summary']
    series = (event.get('Series') or s.get('Series Name') or '').strip()
    track = (event.get('Track') or '').strip()
    drivers = [(d.get('Name') or '').strip() for d in entry['drivers'] if (d.get('Name') or '').strip()]
    if not drivers:
        drivers = [entry_label(entry)] if entry_label(entry) else []

    # the export already knows the season — no need to pass --season by hand
    year, quarter = event.get('Season Year'), event.get('Season Quarter')
    season = f'{year} Season {quarter}' if year and quarter else ''

    rec = {
        'subsession_id': subsession_from_name(path),
        'season': season,
        'date': (event.get('Start Time') or '')[:10],
        'event': series or track,
        'track': track,
        'length': derive_length(series, event.get('Special Event Type')),
        'class': (s.get('Car Class') or '').strip(),
        'car': (s.get('Car') or '').strip(),
        'car_id': as_int(s.get('Car ID')),
        'finish_position': as_int(s.get('Fin Pos')),   # already 1-based in the export
        'starting_position': as_int(s.get('Start Pos')),
        'laps': as_int(s.get('Laps Comp')),
        'laps_led': as_int(s.get('Laps Led')),
        'incidents': as_int(s.get('Inc')),
        'best_lap': (s.get('Fastest Lap Time') or '').strip(),
        'car_number': (s.get('Car #') or '').strip(),
        'sof': as_int(event.get('Strength of Field')),
        'drivers': drivers,
    }
    return rec


def main():
    ap = argparse.ArgumentParser(description='Import iRacing result CSVs into data/races.json')
    ap.add_argument('csvs', nargs='+', help='paths or globs to eventresult_*.csv')
    ap.add_argument('--list', action='store_true',
                    help='print the entries in each file and write nothing')
    ap.add_argument('--season', help='label these races, e.g. "2026 Season 2"')
    args = ap.parse_args()

    paths = []
    for pattern in args.csvs:
        hits = [pathlib.Path(p) for p in glob.glob(pattern)]
        paths.extend(hits or ([pathlib.Path(pattern)] if pathlib.Path(pattern).is_file() else []))
    if not paths:
        print('No CSV files matched.')
        return 1

    cfg = load_team_config()
    existing = json.loads(RACES_JSON.read_text(encoding='utf-8')) if RACES_JSON.is_file() else []
    by_id = {r.get('subsession_id'): r for r in existing if r.get('subsession_id')}
    loose = [r for r in existing if not r.get('subsession_id')]
    written = 0

    for path in paths:
        print(f'{path.name}...')
        rec = build_record(path, cfg, args.list)
        if rec is None:
            continue

        sid = rec.get('subsession_id')
        prior = by_id.get(sid, {}) if sid else {}
        for key in PRESERVE:
            if prior.get(key):
                rec[key] = prior[key]
        if args.season:
            rec['season'] = args.season
        rec = {k: v for k, v in rec.items() if v not in (None, '', [])}

        if sid:
            by_id[sid] = rec
        else:
            loose.append(rec)
        written += 1
        print(f"  ✓ {rec.get('event','?')} — P{rec.get('finish_position','?')} "
              f"· {len(rec.get('drivers', []))} drivers · {rec.get('car','?')}")

    if args.list:
        return 0

    races = sorted(list(by_id.values()) + loose,
                   key=lambda r: str(r.get('date', '')), reverse=True)
    RACES_JSON.parent.mkdir(parents=True, exist_ok=True)
    RACES_JSON.write_text(json.dumps(races, indent=2, ensure_ascii=False) + '\n',
                          encoding='utf-8')
    print(f'\nwrote {written} race(s) — data/races.json now has {len(races)} total')
    return 0


if __name__ == '__main__':
    sys.exit(main())
