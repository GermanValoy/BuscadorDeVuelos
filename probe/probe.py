import json, os, urllib.parse, urllib.request
for o in ("EZE", "SCL"):
    p = dict(engine="google_travel_explore", departure_id=o, arrival_id="MIA", month=2,
             travel_duration=2, currency="USD", hl="es", adults=3, children=1,
             api_key=os.environ["SERPAPI_KEY"])
    d = json.load(urllib.request.urlopen("https://serpapi.com/search.json?" + urllib.parse.urlencode(p), timeout=90))
    print(o, d.get("error"), d.get("start_date"), d.get("end_date"), [f.get("price") for f in d.get("flights", [])])
