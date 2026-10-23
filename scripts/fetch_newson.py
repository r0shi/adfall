import json, urllib.request, urllib.parse, time
UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 Chrome/128 Safari/537.36"
states=["Alabama","Alaska","Arizona","Arkansas","California","Colorado","Connecticut","Delaware","District of Columbia","Florida","Georgia","Hawaii","Idaho","Illinois","Indiana","Iowa","Kansas","Kentucky","Louisiana","Maine","Maryland","Massachusetts","Michigan","Minnesota","Mississippi","Missouri","Montana","Nebraska","Nevada","New Hampshire","New Jersey","New Mexico","New York","North Carolina","North Dakota","Ohio","Oklahoma","Oregon","Pennsylvania","Rhode Island","South Carolina","South Dakota","Tennessee","Texas","Utah","Vermont","Virginia","Washington","West Virginia","Wisconsin","Wyoming","Puerto Rico"]
out={}
for s in states:
    url="https://newson-api.triple-it.nl/v5api/search?query="+urllib.parse.quote(s)+"&platformType=website"
    req=urllib.request.Request(url,headers={"User-Agent":UA})
    try:
        d=json.load(urllib.request.urlopen(req,timeout=30))
    except Exception as e:
        print("ERR",s,e); continue
    n=0
    for r in d.get("results",[]):
        for it in r.get("items",[]):
            if it.get("type")=="STATION":
                out[it["id"]]={"id":it["id"],"name":it["name"],"city":it.get("city"),"state":it.get("state"),"tags":it.get("tags"),"logo":it.get("logoUrl")}
                n+=1
    print(s,n)
    time.sleep(0.4)
json.dump(out,open("dl/newson_stations.json","w"),indent=1)
print("total",len(out))
