# OpMo Endurance — Race Log

A static page showing the endurance races the Operation Motorsport team has run,
with a picture of the car for each one. No backend, no database — `index.html`
reads `data/races.json`.

## Run it locally

```bash
python -m http.server 4790
# then open http://localhost:4790
```

Opening `index.html` straight off disk will not work: the browser blocks the
`fetch` of `data/races.json` on `file://`.

## Adding races — the CSV route (this is the one that works)

On the iRacing results page for a race, use the export button. You get
`eventresult_<subsessionid>_0.csv`. Then:

```bash
# see every team in the race and confirm which one is ours
python scripts/import_results_csv.py --list  eventresult_85426101_0.csv

# import it
python scripts/import_results_csv.py eventresult_85426101_0.csv
```

It pulls date, event, track, class, car, start and finish position, laps, laps
led, incidents, best lap, car number, strength of field, the full driver lineup,
and the season label (derived from the export's season year + quarter).

Which entry is ours comes from `scripts/team.json` — `cust_ids` is checked first
and is the reliable match; `team_names` substrings are the fallback and are what
currently matches "OpMo Enduro Alpha".

> If OpMo ever runs two entries in the same race, the importer takes the first
> match. Add the specific `cust_ids` for the car you want, or import once per
> car and edit `data/races.json` by hand.

Re-importing the same race updates it in place — it never duplicates, and it
never overwrites `livery_image`, `season`, `event`, or `notes` if you edited
them by hand.

### Adding races by hand

Add an object to `data/races.json`. Every field the page reads is documented in
`data/races.example.json`. Only `event` (or `track`) is really required; cards
degrade gracefully as fields go missing.

## Car images

**You supply these.** iRacing's catalog art is only reachable through the Data
API, which is closed to us (see below), so there is no automatic source.

Drop an image in `images/liveries/` named `<subsession_id>.jpg` and point the
race at it:

```json
"livery_image": "images/liveries/85426101.jpg"
```

Good sources, best first:

1. **Clearcoat's Showroom** — load the team livery and grab a still. Cleanest
   result, correct car, correct livery, no HUD.
2. **An iRacing replay screenshot** — free camera, hide the UI, chase or trackside.
3. **A broadcast frame** from the race itself.

Landscape crops near 16:9 look best; the card crops to fill.

If a race has no image the card shows a quiet "no image yet" placeholder rather
than a broken image, so it is safe to import everything now and add pictures
later.

## About the iRacing API (why there's a dead script in here)

`scripts/pull_races.py` and `scripts/iracing_client.py` would pull races
directly by subsession ID. They cannot run right now, and it is not a bug:

- iRacing **removed legacy `/auth`** on 9 December 2025 (2026 Season 1). The
  endpoint now returns HTTP 405. Verified 2026-07-29.
- The replacement is OAuth2, and client IDs are **issued only by iRacing on
  request** — there is no self-service page in account management.
- iRacing has **paused issuing new OAuth client IDs** while they evaluate
  third-party API usage, and say they will announce on the forums when it
  reopens.

The credentials in `operation-motorsport-dashboard/.env` return
`invalid_client` because they were never a real registered client. The request
format itself was verified correct against iRacing's spec (standard base64
masking — the token endpoint explicitly rejects URL-safe base64), so if a client
ID is ever issued, `pull_races.py` should work with only the secret pasted into
`.env`.

Until then the CSV importer is the supported path and needs no credentials at
all.

## Deploying

Push to GitHub and enable Pages on `main`. Everything is static.
