"""
Pull OpMo endurance races into data/races.json from iRacing subsession IDs.

    python scripts/pull_races.py 71234567 71298765
    python scripts/pull_races.py --list-entries 71234567   # who was in that race?

Re-running an ID updates that race in place rather than duplicating it, and
never clobbers a livery_image you set by hand.

Which entry is "ours" comes from scripts/team.json:
    team_names : substrings matched against the team/driver name (case-insensitive)
    cust_ids   : iRacing customer IDs of team drivers — matched against the
                 driver list of each entry, which is what actually works for
                 team events where the team name is inconsistent
Set either or both. If nothing matches, the race is skipped with a message and
--list-entries shows you what was there so you can fix the config.
"""
import argparse
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

from iracing_client import IRacingClient, IRacingError, load_env, write_json  # noqa: E402

RACES_JSON = ROOT / 'data' / 'races.json'
TEAM_JSON = HERE / 'team.json'
CAR_IMG_DIR = ROOT / 'images' / 'cars'
IMAGES_BASE = 'https://images-static.iracing.com'

# fields the site owns and a re-pull must never overwrite
PRESERVE = ('livery_image', 'season', 'event', 'notes')


def load_team_config() -> dict:
    if TEAM_JSON.is_file():
        return json.loads(TEAM_JSON.read_text(encoding='utf-8'))
    return {'team_names': [], 'cust_ids': []}


def race_session(result: dict) -> dict:
    """The race sim-session — not practice or qualifying."""
    sessions = result.get('session_results') or []
    for s in sessions:
        if (s.get('simsession_type_name') or '').lower() == 'race':
            return s
    return sessions[-1] if sessions else {}


def entry_drivers(entry: dict) -> list:
    """Driver names for an entry — team entries nest them, solo entries don't."""
    kids = entry.get('driver_results') or []
    if kids:
        return [d.get('display_name', '') for d in kids if d.get('display_name')]
    return [entry.get('display_name', '')] if entry.get('display_name') else []


def entry_cust_ids(entry: dict) -> list:
    kids = entry.get('driver_results') or []
    if kids:
        return [d.get('cust_id') for d in kids if d.get('cust_id')]
    return [entry['cust_id']] if entry.get('cust_id') else []


def find_our_entry(entries: list, cfg: dict):
    names = [n.lower() for n in cfg.get('team_names', []) if n]
    ids = {int(c) for c in cfg.get('cust_ids', []) if str(c).isdigit()}

    for e in entries:
        if ids and ids.intersection(entry_cust_ids(e)):
            return e
    for e in entries:
        label = (e.get('display_name') or '').lower()
        if names and any(n in label for n in names):
            return e
    return None


def fmt_length(result: dict, entry: dict) -> str:
    """Prefer the scheduled duration; fall back to lap count."""
    for key in ('session_duration', 'race_time_limit_minutes', 'time_limit_minutes'):
        val = result.get(key)
        if isinstance(val, (int, float)) and val > 0:
            minutes = val / 60 if val > 1000 else val   # seconds vs minutes
            hours = minutes / 60
            return f'{hours:.0f}h' if hours >= 1 and abs(hours - round(hours)) < .05 \
                else f'{minutes:.0f} min'
    laps = entry.get('laps_complete')
    return f'{laps} laps' if laps else ''


def car_image(client: IRacingClient, car_id: int, assets_cache: dict) -> str:
    """Cache the stock catalog image for a car into images/cars/<car_id>.jpg."""
    if not car_id:
        return ''
    dest = CAR_IMG_DIR / f'{car_id}.jpg'
    rel = f'images/cars/{car_id}.jpg'
    if dest.is_file():
        return rel

    if not assets_cache:
        try:
            assets_cache.update(client.get('/data/car/assets'))
        except IRacingError as e:
            print(f'  ! could not fetch car assets: {e}')
            return ''

    asset = assets_cache.get(str(car_id)) or assets_cache.get(car_id) or {}
    folder = (asset.get('folder') or '').lstrip('/')
    for key in ('small_image', 'large_image', 'logo'):
        name = asset.get(key)
        if not name:
            continue
        url = f'{IMAGES_BASE}/{folder}/{name}' if folder else f'{IMAGES_BASE}/{name}'
        if client.download(url, dest):
            print(f'  · cached car image -> {rel}')
            return rel
    print(f'  ! no catalog image found for car_id {car_id}')
    return ''


def build_record(client, subsession_id, cfg, assets_cache, list_only=False):
    result = client.get('/data/results/get', subsession_id=subsession_id,
                        include_licenses='false')
    session = race_session(result)
    entries = session.get('results') or []

    if list_only:
        print(f'\nsubsession {subsession_id} — {len(entries)} entries:')
        for e in entries:
            drivers = ', '.join(entry_drivers(e)) or '(no drivers listed)'
            print(f"  P{(e.get('finish_position', -1) + 1):<3} {e.get('display_name','?'):<34} "
                  f"team_id={e.get('team_id','-')}  {drivers}")
        return None

    entry = find_our_entry(entries, cfg)
    if entry is None:
        print(f'  ! no OpMo entry matched in subsession {subsession_id}. '
              f'Run with --list-entries {subsession_id} and update scripts/team.json')
        return None

    track = result.get('track') or {}
    track_name = ' — '.join(filter(None, [track.get('track_name'), track.get('config_name')]))
    car_id = entry.get('car_id') or 0

    # the Data API reports finish_position 0-based
    finish = entry.get('finish_position')
    start = entry.get('starting_position')

    return {
        'subsession_id': int(subsession_id),
        'date': (result.get('start_time') or '')[:10],
        'event': result.get('season_name') or result.get('series_name') or track_name,
        'track': track_name,
        'length': fmt_length(result, entry),
        'class': entry.get('car_class_short_name') or entry.get('car_class_name') or '',
        'car': entry.get('car_name') or '',
        'car_id': car_id,
        'finish_position': (finish + 1) if isinstance(finish, int) and finish >= 0 else None,
        'starting_position': (start + 1) if isinstance(start, int) and start >= 0 else None,
        'laps': entry.get('laps_complete'),
        'incidents': entry.get('incidents'),
        'drivers': entry_drivers(entry),
        'car_image': car_image(client, car_id, assets_cache),
    }


def main():
    ap = argparse.ArgumentParser(description='Pull OpMo races from iRacing into data/races.json')
    ap.add_argument('subsession_ids', nargs='+', type=int)
    ap.add_argument('--list-entries', action='store_true',
                    help='just print every entry in the race, do not write anything')
    ap.add_argument('--season', help='label these races with a season, e.g. "2026 Season 3"')
    args = ap.parse_args()

    load_env(ROOT / '.env',
             pathlib.Path.home() / 'operation-motorsport-dashboard' / '.env')

    client = IRacingClient()
    try:
        client.login()
    except IRacingError as e:
        print(f'ERROR: {e}')
        return 1

    cfg = load_team_config()
    existing = json.loads(RACES_JSON.read_text(encoding='utf-8')) if RACES_JSON.is_file() else []
    by_id = {r.get('subsession_id'): r for r in existing}
    assets_cache = {}
    written = 0

    for sid in args.subsession_ids:
        print(f'subsession {sid}...')
        try:
            rec = build_record(client, sid, cfg, assets_cache, args.list_entries)
        except IRacingError as e:
            print(f'  ! {e}')
            continue
        if rec is None:
            continue

        prior = by_id.get(sid, {})
        for key in PRESERVE:                     # never clobber hand-edited fields
            if prior.get(key):
                rec[key] = prior[key]
        if args.season:
            rec['season'] = args.season
        rec = {k: v for k, v in rec.items() if v not in (None, '', [])}

        by_id[sid] = rec
        written += 1
        print(f"  ✓ {rec.get('event','?')} — P{rec.get('finish_position','?')} "
              f"({len(rec.get('drivers', []))} drivers)")

    if args.list_entries:
        return 0

    races = sorted(by_id.values(), key=lambda r: str(r.get('date', '')), reverse=True)
    write_json(RACES_JSON, races)
    print(f'\nwrote {written} race(s) — data/races.json now has {len(races)} total')
    return 0


if __name__ == '__main__':
    sys.exit(main())
