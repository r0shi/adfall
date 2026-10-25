#!/usr/bin/env python3
"""Load stations (web/data/stations.json) into the Postgres `station` table.

Idempotent: rows are upserted by facility_id. Run once after a stations.json refresh (`make stations`);
the crawl refuses stations that are not in this table, so the licensed-station list stays the one
source of what gets crawled.
  python3 -m ingest.stations

station_group is derived from the licensee string with the rules in GROUPS (checked against every licensee
in the station table: the large groups use dozens of licensee entities, e.g. Sinclair's "<CALL> Licensee, LLC",
Allen Media's "<City> TV License Company, LLC", Tegna's legacy Belo/Gannett companies). Stations no rule
matches get "Independent", public and religious broadcasters are grouped as such; NULL means unknown.
"""
import argparse, json, logging, os, re
from . import db
from .runlog import Stage

log = logging.getLogger("ingest.stations")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

GROUPS = [  # (licensee regex, station group); first match wins, so specific company names come before generic shapes
    (r"hearst", "Hearst"),
    (r"tegna|pacific and southern|\bsander\b|king broadcasting|multimedia holdings|multimedia entertainment|multimedia ksdk|combined communications of oklahoma|"
     r"\b(?:wfmy|wcnc-tv|khou-tv|kens-tv|wfaa-tv|wbir-tv|wkyc-tv|kxtv|wusa-tv|wwl-tv|kvue|wtol|wvec|kfmb-tv|kong-tv|kttu-tv|wbns-tv|wtsp|wgrz|kgw|kare|kpnx|wzzm|wxia|wcsh|wlbz|wmaz|ktvb|kmsb|kiii|kcen|kagh|kbmt|kytx|wtic|wtlv|wjxx|wltx|wnep|wpmt|wqad|khq|kthv|wvbt|wwcp)\b.*(?:television|tv|llc|inc)|belo", "Tegna"),
    (r"nexstar|tribune|mission broadcasting|white knight|\bkplr\b|wdaf license|vaughan media|marshall broadcasting", "Nexstar"),
    (r"sinclair|chesapeake|cunningham|deerfield|howard stirk|\bhsh\b|\bkdsm\b|harrisburg licensee|nashville license holdings|"
     r"^[wk][a-z]{2,4}(?:-tv)? licensee,? (?:llc|l\.?l\.?c\.?|l\.?p\.?|inc\.?)$|\([wk][a-z]{2,4}-tv\) licensee", "Sinclair"),
    (r"gray ", "Gray"), (r"scripps", "Scripps"),
    (r"\bcbs\b|viacom|paramount|television station [wk][a-z]{3,4}|^(?:[a-z ]+ )?television station [wk]|los angeles television station|kstw", "CBS"),
    (r"\bnbc\b|comcast|telemundo|station venture operations|universal television", "NBCUniversal"),
    (r"fox television|new world communications|fox tv|nw communications|wfxt|fox stations", "Fox"),
    (r"\babc\b|disney|american broadcasting|wtvd television|wpvi television|kgo television|wls television|ktrk television|kfsn television", "ABC"),
    (r"cox media|cox television|georgia television|wsoc television|^wpxi, llc|kiro-tv|wftv, llc|wsb|kirc", "Cox"),
    (r"graham media", "Graham"),
    (r"hubbard|kstp-tv|kstc-tv|wdio-tv|wnyt-tv|kob-tv|kaal-tv|ksax-tv|kobr|kobf|wtop", "Hubbard"),
    (r"allen media|^allen |tv license company", "Allen Media"),
    (r"ion television|ion media", "Ion"),
    (r"univision|televisa|unimas|unvision|license partnership", "Univision"),
    (r"entravision", "Entravision"),
    (r"estrella television|liberman", "Estrella"),
    (r"weigel|wdjt-tv|^tv-49|wmei-tv|wciu-tv|wmlw", "Weigel"),
    (r"queenb television|television wisconsin|morgan murphy", "Morgan Murphy"),
    (r"marquee broadcasting", "Marquee"),
    (r"lilly broadcasting|sjl of|^wzmq", "Lilly"),
    (r"capitol broadcasting|wraz-tv", "Capitol"),
    (r"heritage broadcasting|cadillac telecasting", "Heritage"),
    (r"morris network|morris multimedia|wway-tv", "Morris"),
    (r"sarkes tarzian", "Sarkes Tarzian"),
    (r"bahakel|(?:north carolina|alabama|south carolina|springfield) broadcasting partners", "Bahakel"),
    (r"\bkhq\b|cowles|spokane television", "Cowles"),
    (r"npg of|news-press", "News-Press & Gazette"),
    (r"rincon broadcasting", "Rincon"),
    (r"tidewater tv|lockwood|augusta tv llc", "Lockwood"),
    (r"sagamorehill", "SagamoreHill"),
    (r"hc2 station group|innovate", "HC2"),
    (r"inyo broadcast", "Inyo"),
    (r"^rnn\b", "RNN"),
    (r"sunbeam television|whdh-tv", "Sunbeam"),
    (r"draper media", "Draper"),
    (r"block communications|wdrb|wand", "Block"),
    (r"evening post|cordillera", "Cordillera"),
    (r"gocom media", "GOCOM"),
    (r"byrne acquisition", "Byrne"),
    (r"imagicomm", "Imagicomm"),
    (r"bonten|esteem", "Bonten"),
    (r"saga communications", "Saga"),
    (r"forum communications", "Forum"),
    (r"quincy", "Quincy"),
    (r"maranatha", "Maranatha"),
    (r"waterman|fort myers broadcasting", "Waterman"),
    (r"londen|^kazt", "Londen"),
    (r"public broadcasting|public media|public television|public telecommunications|public tv|educational|board of education|university|college|regents|state of|"
     r"commission|school board|school district|\bpbs\b|^wnet|whyy|kqed|ideastream|window to the world|friends of ksps|vpm media|wqed|wjct|ktoo|kvie|^kqed|"
     r"community television (?:educators|inc)|cascade public|twin cities public|alaska public|detroit public|nashville public|colorado public|minority television|"
     r"telecommunications council|department of information technology|county board|ocean state media|wskg|mountain lake|blue ridge public|"
     r"metropolitan indianapolis|st\. louis regional|rocky mountain public|southern oregon public|smoky hills|public communications|public tele|"
     r"ana g\. mendez|tougaloo|vincennes|amarillo junior|technical college|community college|unified school|educators broadcasting|hawaii public", "Public"),
    (r"trinity|christian|ministries|daystar|religious|catholic|church|gospel|\bfaith\b|evangel|bible|word of god|sonshine|three angels|cornerstone television|"
     r"good news|kingdom broadcasting|harvest|victory television|agape|life of victory|cristo|ebenezer|proclaim|vcy america|cadena del milagro|real life network|"
     r"blue mountain broadcasting|watchmen|son broadcasting|family broadcasting|good life|amka|better life television|hour of|pentecostal|first united|"
     r"community broadcast group|salem media|family entertainment television|lighthouse|western new life|sonlife|ctn\b|golden state broadcasting", "Religious"),
]


def station_group(licensee):
    l = (licensee or "").lower().strip()
    if not l:
        return None
    for rx, g in GROUPS:
        if re.search(rx, l):
            return g
    return "Independent"


def wkt_multipolygon(polys):
    rings = []
    for poly in polys:
        pts = ",".join(f"{lon} {lat}" for lat, lon in poly)
        rings.append(f"(({pts}))")
    return "MULTIPOLYGON(" + ",".join(rings) + ")"


def load_stations(con, st):
    d = json.load(open(os.path.join(ROOT, "web", "data", "stations.json")))
    rows = []
    groups = {}
    for s in d["stations"]:
        g = station_group(s["licensee"])
        groups[g] = groups.get(g, 0) + 1
        rows.append((s["fac"], s["call"], s["svc"], s["city"], s["state"], s["licensee"], g,
                     s["rf"], s["vchan"], f"POINT({s['tx'][1]} {s['tx'][0]})", wkt_multipolygon(s["polys"]),
                     (s.get("newson") or {}).get("id"), s["slug"]))
    with con.cursor() as cur:
        cur.executemany("""INSERT INTO station(facility_id,call,service,city,state,licensee,station_group,rf_channel,virtual_channel,tx,contour,newson_id,public_file_slug)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,ST_GeomFromText(%s,4326),ST_Multi(ST_MakeValid(ST_GeomFromText(%s,4326))),%s,%s)
            ON CONFLICT (facility_id) DO UPDATE SET call=EXCLUDED.call, service=EXCLUDED.service, city=EXCLUDED.city, state=EXCLUDED.state,
              licensee=EXCLUDED.licensee, station_group=EXCLUDED.station_group, rf_channel=EXCLUDED.rf_channel, virtual_channel=EXCLUDED.virtual_channel,
              tx=EXCLUDED.tx, contour=EXCLUDED.contour, newson_id=EXCLUDED.newson_id, public_file_slug=EXCLUDED.public_file_slug, updated_at=now()""", rows)
    con.commit()
    st.count("stations", len(rows))
    log.info("stations: %d; groups: %s", len(rows), ", ".join(f"{g}={n}" for g, n in sorted(groups.items(), key=lambda x: -x[1])[:12]))


def main(argv=None):
    ap = argparse.ArgumentParser()
    a = ap.parse_args(argv)
    with Stage("stations", args=vars(a)) as st, db.connect() as con:
        load_stations(con, st)


if __name__ == "__main__":
    main()
