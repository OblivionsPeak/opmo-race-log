# Team livery images

Drop a picture of the actual car here and it overrides the stock iRacing
catalog art for that race.

**Naming:** `<subsession_id>.jpg` — e.g. `71234567.jpg`.

Then point the race at it in `data/races.json`:

```json
"livery_image": "images/liveries/71234567.jpg"
```

The puller never overwrites `livery_image`, so re-pulling a race keeps your
image. Landscape crops around 16:9 look best — the card crops to fill.

Good sources: an iRacing replay screenshot, a Clearcoat showroom render, or a
photo from the broadcast.
