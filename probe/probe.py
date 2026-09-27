import json, os, urllib.parse, urllib.request, urllib.error
KEY = os.environ["SERPAPI_KEY"]
def call(params):
    params = dict(params, api_key=KEY)
    url = "https://serpapi.com/search.json?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=90) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return json.loads(e.read() or b"{}") | {"http": e.code}
def show(name, d):
    print("=====", name)
    print("keys:", list(d.keys()))
    if "error" in d: print("ERROR:", d["error"])
    print("params:", json.dumps(d.get("search_parameters", {}))[:600])
    for k, v in d.items():
        if k in ("search_metadata", "search_parameters"): continue
        s = json.dumps(v, ensure_ascii=False)
        print(f"--- {k} ({type(v).__name__}, len {len(v) if hasattr(v,'__len__') else '-'}):")
        print(s[:2500])
base = dict(engine="google_travel_explore", departure_id="EZE", arrival_id="MIA",
            currency="USD", hl="es", adults=3, children=1)
show("explore month=2 dur=3", call(base | dict(month=2, travel_duration=3)))
