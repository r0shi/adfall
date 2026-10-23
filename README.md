# TV Wormhole

Prototype: pick any spot in the US and see which broadcast TV stations reach it
(FCC predicted service contours), with a link to each station's live newscast
stream on NewsON and to its FCC political advertising file.

## Run

```bash
python3 -m http.server 8765 --directory web
```

Then open http://localhost:8765.

## Rebuild the data

`web/data/stations.json` is generated from public FCC data plus the NewsON
station list. To refresh it:

1. Download the FCC contour file (updated daily):
   https://transition.fcc.gov/bureaus/mb/databases/map/TV_service_contour_current.zip
2. Export TV Query pipe-delimited lists per state for services `DTV` and `DCA`
   into a folder (`tvq?state=IA&serv=DTV&vac=3&list=4&size=9`).
3. `python3 scripts/fetch_newson.py` (writes `dl/newson_stations.json`).
4. `python3 scripts/build_data.py --tvq-dir RAW/tvq --contour RAW/TV_service_contour_current.txt --newson RAW/newson_stations.json --out web/data/stations.json`

## What it does not do

* Network affiliation is not in the FCC TV Query export, so stations show call
  sign and channel only.
* Streams are linked, not embedded. Station streams replace broadcast ad breaks
  with a slate, so political ads are not visible on them; the FCC political file
  link is the substitute.
