"""Name normalization shared by identity (buyer merging) and aggregate (folder parsing)."""
import re

STATES = {"AL":"ALABAMA","AK":"ALASKA","AZ":"ARIZONA","AR":"ARKANSAS","CA":"CALIFORNIA","CO":"COLORADO","CT":"CONNECTICUT","DE":"DELAWARE","FL":"FLORIDA","GA":"GEORGIA","HI":"HAWAII","ID":"IDAHO","IL":"ILLINOIS","IN":"INDIANA","IA":"IOWA","KS":"KANSAS","KY":"KENTUCKY","LA":"LOUISIANA","ME":"MAINE","MD":"MARYLAND","MA":"MASSACHUSETTS","MI":"MICHIGAN","MN":"MINNESOTA","MS":"MISSISSIPPI","MO":"MISSOURI","MT":"MONTANA","NE":"NEBRASKA","NV":"NEVADA","NH":"NEW HAMPSHIRE","NJ":"NEW JERSEY","NM":"NEW MEXICO","NY":"NEW YORK","NC":"NORTH CAROLINA","ND":"NORTH DAKOTA","OH":"OHIO","OK":"OKLAHOMA","OR":"OREGON","PA":"PENNSYLVANIA","RI":"RHODE ISLAND","SC":"SOUTH CAROLINA","SD":"SOUTH DAKOTA","TN":"TENNESSEE","TX":"TEXAS","UT":"UTAH","VT":"VERMONT","VA":"VIRGINIA","WA":"WASHINGTON","WV":"WEST VIRGINIA","WI":"WISCONSIN","WY":"WYOMING","DC":"DISTRICT OF COLUMBIA"}
STATE_WORDS = set(STATES) | {w for n in STATES.values() for w in n.split()}
PARTY = {"DCCC","NRCC","DSCC","NRSC","RNC","DNC","DEM","DEMO","DEMOCRAT","DEMOCRATS","DEMOCRATIC","REP","REPUBLICAN","REPUBLICANS","GOP","D","R","IND","INDEPENDENT","PARTY","CAUCUS","HDCC","PAHDCC","NCHRC","SDCC","HRCC","SRCC","ADCC","RSCC","RSLC","DLCC"}
OFFICE = {"FOR","US","U","S","CONGRESS","CONGRESSIONAL","SENATE","SENATOR","HOUSE","REPRESENTATIVE","REPRESENTATIVES","REP","DISTRICT","DIST","CD","HD","SD","AD","GOVERNOR","GOV","LT","LIEUTENANT","ATTORNEY","GENERAL","AG","AUDITOR","TREASURER","SECRETARY","SOS","STATE","SUPERINTENDENT","PUBLIC","EDUCATION","INSTRUCTION","ASSEMBLY","ASSEMBLYMAN","ASSEMBLYWOMAN","COMMISSIONER","COMMISSION","PSC","SUPERVISOR","COUNTY","MAYOR","JUDGE","JUSTICE","SUPREME","COURT","RECORDER","SHERIFF","CLERK","COUNCIL","SCHOOL","BOARD","OFFICE","SEAT","LABOR","AGRICULTURE","INSURANCE","CORPORATION","REGENT","PRESIDENT","MAJORITY","LEADER","GUBERNATORIAL","SENATORIAL","STATEWIDE","LEGISLATIVE","JUDICIAL","MUNICIPAL","FEDERAL","LOCAL","CANDIDATES","RACE","RACES","ELECTION"}
GENERIC = {"COMMITTEE","TO","ELECT","FRIENDS","OF","CAMPAIGN","VICTORY","FUND","DR","MR","MRS","MS","TEAM","VOTE","VOTES","WITH","TOGETHER","PRIMARY","RUNOFF","ISSUE","ORDER","EST","REV","FLIGHT","THE","AND","A","AN","IN","ON","AT","BY","NAB","PB","19","INC","LLC","CO","CORP","AUTHORIZED","FOLDER","MOVED","CANDIDATE","POLITICAL","POL","NCCI","ADS","AD","TV","2026","26","25","2025","HYBRID","COORDINATED","JOINT","FUNDRAISING","JFC","NON","CAND"}
NOISE_RX = re.compile(r"\b\d[\d./-]*\b")      # numbers, dates, order numbers

def norm(s):
    s = (s or "").upper().replace("&", " AND ")
    s = re.sub(r"[^A-Z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()

def name_tokens(label):
    """Tokens that could be a person's or organization's name, after stripping party/office/state/noise."""
    toks = norm(NOISE_RX.sub(" ", label)).split()
    return [t for t in toks if t not in PARTY and t not in OFFICE and t not in GENERIC and t not in STATE_WORDS and len(t) > 1]

def org_key(label):
    toks = [t for t in norm(NOISE_RX.sub(" ", label)).split() if t not in {"INC","LLC","CO","CORP","THE","ISSUE","EST","ORDER","FLIGHT","REV","PAC"}]
    return " ".join(toks)

def title(s):
    small = {"OF","FOR","AND","THE","TO","IN","ON","BY","A","AN"}
    out = []
    for i, w in enumerate(s.split()):
        if w in {"PAC","USA","LLC","INC","US","GOP","NRA","AFL","CIO","II","III","IV","DC","AZ","NC","PA","MI","WI","NV","GA","IA"}: out.append(w)
        elif w in small and i: out.append(w.lower())
        elif "-" in w: out.append("-".join(p.capitalize() for p in w.split("-")))
        else: out.append(w.capitalize())
    return " ".join(out)



ORG_STOP = {"THE", "OF", "FOR", "AND", "A", "AN", "TO", "IN", "INC", "LLC", "PAC", "FUND", "COMMITTEE", "ACTION", "ISSUE", "EST", "ORDER", "FLIGHT", "REV"}


def org_tokens(label):
    """Tokens that distinguish an organization name (keeps office words like HOUSE/SENATE/MAJORITY)."""
    return [t for t in norm(NOISE_RX.sub(" ", label)).split() if t not in ORG_STOP and len(t) > 1]


NICKNAMES = [("RICHARD", "RICK", "DICK", "RICH"), ("MICHAEL", "MIKE"), ("ROBERT", "BOB", "ROB", "BOBBY"), ("JOSEPH", "JOE", "JOEY"), ("WILLIAM", "BILL", "WILL", "BILLY"),
             ("JAMES", "JIM", "JIMMY"), ("THOMAS", "TOM", "TOMMY"), ("JONATHAN", "JON"), ("JOSHUA", "JOSH"), ("CHRISTOPHER", "CHRIS"), ("DANIEL", "DAN", "DANNY"),
             ("MATTHEW", "MATT"), ("ANDREW", "ANDY", "DREW"), ("ANTHONY", "TONY"), ("ELIZABETH", "LIZ", "BETH", "BETSY"), ("KATHERINE", "KATE", "KATIE", "KATHY", "KATHRYN"),
             ("JENNIFER", "JEN", "JENNY"), ("PATRICIA", "PAT", "PATTY"), ("EDWARD", "ED", "EDDIE"), ("BENJAMIN", "BEN"), ("SAMUEL", "SAM"), ("TIMOTHY", "TIM"),
             ("NICHOLAS", "NICK"), ("STEVEN", "STEVE", "STEPHEN"), ("JEFFREY", "JEFF"), ("GREGORY", "GREG"), ("KENNETH", "KEN"), ("RONALD", "RON"), ("DONALD", "DON"),
             ("CHARLES", "CHARLIE", "CHUCK"), ("ZACHARY", "ZACH", "ZACK"), ("DAVID", "DAVE"), ("JOHN", "JOHNNY", "JACK"), ("PETER", "PETE"), ("ALEXANDER", "ALEX"),
             ("REBECCA", "BECKY"), ("MARGARET", "MEG", "PEGGY", "MAGGIE"), ("SUSAN", "SUE", "SUSIE"), ("DEBORAH", "DEB", "DEBBIE"), ("ABDUL", "ABDULRAHMAN"),
             ("NATHANIEL", "NATE", "NATHAN"), ("MARIANNETTE", "MARIANNETTE"), ("THEODORE", "TED"), ("FRANCIS", "FRANK"), ("LAWRENCE", "LARRY"), ("RAYMOND", "RAY"),
             ("DOUGLAS", "DOUG"), ("JACOB", "JAKE"), ("MAXIMILIAN", "MAX"), ("VINCENT", "VINCE"), ("BRADLEY", "BRAD"), ("RANDALL", "RANDY"), ("TERRENCE", "TERRY")]
NICK = {}
for grp in NICKNAMES:
    for n in grp:
        NICK[n] = grp[0]


def first_key(tok):
    return NICK.get(tok, tok)
