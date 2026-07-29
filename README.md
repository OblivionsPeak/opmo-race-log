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

## Adding races

### Automatically, from iRacing

```bash
cp .env.example .env          # fill in your iRacing OAuth credentials
python scripts/pull_races.py --list-entries 71234567    # see who was in the race
# put your drivers' cust_ids into scripts/team.json, then:
python scripts/pull_races.py 71234567 71298765 --season "2026 Season 3"
```

The puller finds your team's entry, writes the record into `data/races.json`,
and caches the stock car image into `images/cars/`. Re-running an ID updates
that race in place — it never duplicates, and it never overwrites `livery_image`,
`season`, `event`, or `notes` if you edited them by hand.

**Requires an iRacing OAuth client authorised for the `password_limited`
grant** — see "Auth" below.

### By hand

Add an object to `data/races.json`. Every field the page reads is documented in
`data/races.example.json`. Only `event` (or `track`) is really required; the
card degrades gracefully as fields go missing.

## Car images

Two sources, livery wins:

1. **`livery_image`** — a real picture of the team car. Drop it in
   `images/liveries/` (see the README there). Displayed edge-to-edge.
2. **`car_image`** — the stock iRacing catalog art, cached automatically by the
   puller into `images/cars/<car_id>.jpg`. Displayed on a light backdrop
   because the catalog art is a cutout.

If neither exists the card shows a quiet "no image yet" placeholder rather than
a broken image.

## Auth

`scripts/iracing_client.py` uses iRacing's OAuth2 `password_limited` grant. The
credential masking is `base64(sha256(value + identifier.trim().lower()))` with
**standard** base64 — the token endpoint explicitly rejects URL-safe base64.

As of 2026-07-29 this returns `invalid_client` with the credentials in
`operation-motorsport-dashboard/.env`. The request format was verified correct
against iRacing's spec, so the fix is on the account side:

1. Open <https://oauth.iracing.com/accountmanagement> and confirm the OAuth
   client still exists and is enabled.
2. Confirm it is authorised for the **`password_limited`** grant. iRacing does
   not enable that grant by default — it is granted per client on request.
3. Regenerate the client secret and paste it into `.env`.

Until that is sorted the puller cannot run, but the site works fine with
hand-entered races.

## Deploying

Push to GitHub and enable Pages on `main`. Everything is static.
