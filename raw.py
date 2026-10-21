#!/usr/bin/env python3
"""Script-only news page (no AI): fetch feeds, merge look-alike headlines,
rank by how many outlets carry a story, write public/index.html.
Published by .github/workflows/news.yml to https://blueline11.github.io/News/

Usage:  python raw.py            (fetches first, then renders)
        python raw.py --no-fetch (render from the existing snapshot.json)
Runs on GitHub Actions every 30 minutes; a local run is only for testing.
"""
import json
import math
import os
import re
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from html import escape

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.environ.get("NEWS_OUT") or os.path.join(BASE, "public", "index.html")
try:
    from zoneinfo import ZoneInfo
    CT = ZoneInfo("America/Chicago")  # handles daylight saving
except Exception:
    CT = timezone(timedelta(hours=-6))
sys.path.insert(0, BASE)  # trusted: our own folder (python -I drops it)
from markets import BOARD_CSS  # noqa: E402

# how-to-refresh line under the title; the web copy sets its own
HINT = os.environ.get("NEWS_HINT", "Updates by itself every 30 minutes.")
CAP = 20
TABS = ["Finance", "Markets", "Top", "World", "US", "Texas", "Tech", "Science", "Turkiye", "Culture", "Sports"]

# Finance tab sub-groups, matched on the headline in this order; the last one takes the rest
FIN_GROUPS = [
    ("Fed & rates", re.compile(r"\b(fed|federal reserve|powell|rate (hike|cut)s?|interest rates?|treasur\w*|"
                               r"yields?|central bank|ecb|bank of (japan|england|canada)|boj|boe)\b", re.I)),
    ("Economic data", re.compile(r"\b(inflation|cpi|ppi|jobs report|payrolls?|unemployment|jobless|gdp|"
                                 r"retail sales|pmi|consumer (confidence|sentiment|spending)|housing starts|"
                                 r"home sales|homebuilders?|recession|economy|economic)\b", re.I)),
    ("Energy & commodities", re.compile(r"\b(oil|crude|brent|opec\+?|natural gas|lng|gasoline|diesel|fuel|"
                                        r"gold|silver|copper|commodit\w*|hormuz|refiner\w*|tankers?)\b", re.I)),
    ("Policy, trade & geopolitics", re.compile(r"\b(tariffs?|sanctions?|trade (deal|war|talks)|export (ban|controls?)|"
                                               r"embargo|stimulus|budget|deficit|debt|shutdown|subsid\w*)\b", re.I)),
    ("Companies & markets", None),
]
# World/US stories that also belong under Finance
MARKET_PULL = re.compile(r"\b(oil|crude|brent|opec|hormuz|tariffs?|sanctions?|trade (deal|war|talks)|"
                         r"fed|federal reserve|central bank|bond yields?|treasury yields?|"
                         r"export (ban|controls?)|stock markets?|wall st(reet)?)\b", re.I)
TITLES = {"Top": "Top stories", "Texas": "Texas & Austin", "Tech": "Tech", "Science": "Science & Health",
          "Turkiye": "Türkiye"}

# headlines that are never news
JUNK = re.compile(
    r"obituary|realtor\.com|scores, news & stats|^\S+ - spectrum news|tierra's texas|"
    r"specimen tree delivery|tickets to this weekend|who am i\?|today's other quizzes|"
    r"gossip|ratings$|team of the week|photo highlights|\.jpg|announces?|introduces|"
    r"launches online|co-marketing|partnership to advance|world's smallest|"
    r"the afp top 10|afp recognizes|^watch:|all the goals|best plays|morning news brief|"
    r"morning bid|commentary:|press review|enforcement actions? with|"
    r"termination of enforcement|best .{0,30}stocks? (right now|to buy)|stocks? to watch (today|this week)|stocks moving in", re.I)

STOP = set("""a an the of to in on for and or as at by with from after over amid into
is are was were be been its it his her their this that new says say said will could
may might us u.s. vs v not no more than up out about how why what who when where
live news update""".split())


SYN = {"french": "france", "paris": "france", "ukrainian": "ukraine", "kyiv": "ukraine",
       "russian": "russia", "moscow": "russia", "kremlin": "russia", "israeli": "israel",
       "iranian": "iran", "tehran": "iran", "chinese": "china", "beijing": "china",
       "saudi": "saudi", "riyadh": "saudi", "houthis": "houthi", "yemeni": "yemen",
       "albanian": "albania", "albertans": "alberta", "kenyan": "kenya", "korean": "korea",
       "seoul": "korea", "pyongyang": "korea", "indian": "india", "japanese": "japan",
       "tokyo": "japan", "turkish": "turkey", "türkiye": "turkey", "british": "britain",
       "uk": "britain", "riots": "riot", "rioting": "riot", "protesters": "protest",
       "protests": "protest", "curfews": "curfew"}

# Google-News wire items all arrive as "World"; move obvious sport/business ones
SPORT = re.compile(r"\b(nfl|nba|wnba|mlb|nhl|world series|alcs|nlcs|premier league|champions league|"
                   r"fifa|uefa|infantino|quarterback|qb|touchdown|tennis|golf(?! course)|cricket|odi|rugby|"
                   r"grand prix|formula 1|f1|ronaldo|mourinho|coach|playoffs?|league|striker|"
                   r"olympic|gymnastics|boxing|ufc|49ers|rays|brewers|eagles|dodgers)\b", re.I)
ECON = re.compile(r"\b(shares|stocks?|wall st|nasdaq|ftse|profit|earnings|ipo|forecast|"
                  r"oil prices|brent|bond yields?|fed|central bank|rate (hike|cut)s?|"
                  r"acquire|acquisition|billion deal|layoffs|job cuts|cut jobs|"
                  r"sterling|euro |yen|dollar|gold eases|inflation)\b", re.I)
US_DOM = re.compile(
    r"\b(congress\w*|senate|senators?|house (speaker|republicans|democrats|vote)|supreme court|"
    r"federal (judge|court|appeals court|prosecutors?|agents?|government|workers)|white house|"
    r"midterms?|democrats?|republicans?|gop|pentagon|fbi|doj|justice department|"
    r"homeland security|ice (agents?|detention|custody|facility)|border patrol|deportations?|"
    r"medicaid|medicare|social security|irs|epa|fema|national guard|trump administration|"
    r"alabama|alaska|arizona|arkansas|california|colorado|connecticut|delaware|florida|hawaii|"
    r"idaho|illinois|indiana|iowa|kansas|kentucky|louisiana|maine|maryland|massachusetts|"
    r"michigan|minnesota|mississippi|missouri|montana|nebraska|nevada|new hampshire|new jersey|"
    r"new mexico|new york|north carolina|north dakota|ohio|oklahoma|oregon|pennsylvania|"
    r"rhode island|south carolina|south dakota|tennessee|texas|utah|vermont|virginia|"
    r"west virginia|wisconsin|wyoming|chicago|los angeles|san francisco|philadelphia|boston|"
    r"seattle|atlanta|miami|detroit|minneapolis|washington,? d\.?c\.?)\b", re.I)
BIZ = re.compile(
    r"\b(market|stocks?|shares|bonds?|treasur\w*|yields?|investors?|traders?|banks?|banking|"
    r"funds?|hedge|private credit|credit|debt|ipo|deal|stake|buys?|sells?|acquir\w*|merger|"
    r"spins? off|billion|million|profit|earnings|revenue|sales|outlook|forecast|ceo|"
    r"crude|oil|gas|gold|copper|commodit\w*|currenc\w*|dollar|yen|euro|yuan|rupee|"
    r"inflation|rates?|central bank|economy|economic|gdp|tariffs?|exports?|imports?)\b", re.I)
# Anadolu also covers world news; keep only its Turkey stories
TR = re.compile(r"(türkiye|turkey|turkish|erdo[gğ]an|ankara|istanbul|izmir)", re.I)
TX = re.compile(r"\b(texas|austin|travis|abbott|paxton|houston|dallas|san antonio|"
                r"round rock|cota|longhorns|ut |hays|williamson|txdot|ercot)\b", re.I)


def resection(it, t):
    sec = it["section"]
    if it["source"] == "Austin local" and not TX.search(t):
        return None  # wire copy republished by a local site; it is covered elsewhere
    if it["source"] == "Anadolu" and not TR.search(t):
        return None
    if it["source"] == "Bloomberg" and BIZ.search(t):
        return "Finance"
    if sec in ("World", "US"):
        if SPORT.search(t):
            return "Sports"
        if ECON.search(t):
            return "Finance"
        if sec == "World" and US_DOM.search(t):
            return "US"
    return "Finance" if sec == "Economy" else sec


def fmt(d, f):
    """strftime with %#I = hour without leading zero, on Windows and Linux alike."""
    return d.strftime(f.replace("%#I", str(int(d.strftime("%I")))))


def clean_title(it):
    t = it["title"]
    t = re.sub(r"^STAT\+:\s*", "", t)  # STAT's paywall marker
    if it["outlet"]:  # Google News appends " - Outlet"
        t = re.sub(r"\s+-\s+[^-]+$", "", t)
        t = re.sub(r"\s+-\s+[^-]*\((NASDAQ|NYSE|AMEX|OTC|NYSEAMERICAN|CBOE)[^)]*\)$", "", t)
    return t.strip()


def words(t):
    t = t.lower().replace("’", "'")
    toks = re.findall(r"[a-z0-9]+(?:'[a-z]+)?", t)
    out = set()
    for w in toks:
        w = re.sub(r"'s$", "", w)
        if w in STOP or len(w) < 3:
            continue
        w = SYN.get(w, w)
        out.add(w[:6])  # crude stem: zelensky/zelenskiy/zelenskyy, curfew/curfews
    return out


def label(it):
    s = it["source"]
    if s.startswith("BBC"):
        return "BBC"
    if s.startswith("NPR"):
        return "NPR"
    if s in ("WSJ", "Bloomberg", "Benzinga"):
        return s
    if s.startswith(("Reuters", "AP", "AFP")) and it["outlet"]:
        base = s.split(" ")[0]
        o = it["outlet"]
        return base if o.lower().startswith((base.lower(), "afp.com", "ap news")) else o
    if s == "Austin local":
        return it["outlet"] or "Local"
    for brand in ("CNBC", "MarketWatch"):
        if s.startswith(brand):
            return brand
    return {"SCMP Asia": "SCMP", "Federal Reserve": "Fed", "Hurriyet Daily News": "Hürriyet DN",
            "Anadolu": "Anadolu (AA)"}.get(s, s)


def main():
    if "--no-fetch" not in sys.argv:
        subprocess.run([sys.executable, "-I", os.path.join(BASE, "fetch-feeds.py"), "30"],
                       check=False, stdout=subprocess.DEVNULL)
    snap = json.load(open(os.path.join(BASE, "snapshot.json"), encoding="utf-8"))

    items = []
    for it in snap["items"]:
        t = clean_title(it)
        if not t or JUNK.search(t):
            continue
        sec = resection(it, t)
        if sec is None:
            continue
        it = dict(it, title=t, w=words(t), label=label(it), section=sec)
        if len(it["w"]) < 2:
            continue
        items.append(it)

    # greedy clustering on headline word overlap, rare words weighted higher (idf)
    df = {}
    for it in items:
        for w in it["w"]:
            df[w] = df.get(w, 0) + 1
    N = len(items)
    idf = {w: math.log(N / d) for w, d in df.items()}

    def wsum(ws):
        return sum(idf.get(w, 0) for w in ws)

    clusters = []
    for it in items:  # newest first
        best, score = None, 0.0
        for c in clusters:
            shared = it["w"] & c["lead_w"]
            if len(shared) < 2:
                continue
            j = wsum(shared) / max(1e-9, min(wsum(it["w"]), wsum(c["lead_w"])))
            if j >= 0.42 and j > score:
                best, score = c, j
        if best:
            best["items"].append(it)
            best["w"] |= it["w"]
        else:
            clusters.append({"items": [it], "w": set(it["w"]), "lead_w": set(it["w"])})

    for c in clusters:
        c["labels"] = []
        for it in c["items"]:
            if it["label"] not in c["labels"]:
                c["labels"].append(it["label"])
        c["n"] = len(c["labels"])
        # lead item: one with a real summary, else newest
        c["lead"] = next((i for i in c["items"] if len(i["summary"]) > 40), c["items"][0])
        secs = [i["section"] for i in c["items"]]
        c["section"] = max(set(secs), key=secs.count)
        c["time"] = max(i["published"] for i in c["items"])

    def story(c, show_sec=False):
        lead = c["lead"]
        seen, links = set(), []
        for it in c["items"]:
            if it["label"] in seen:
                continue
            seen.add(it["label"])
            links.append(f'<a href="{escape(it["url"])}" target="_blank" rel="noopener">{escape(it["label"])}</a>')
        d = datetime.fromisoformat(c["time"]).astimezone(CT) if c["time"] else None
        t = (f'<time datetime="{d.isoformat()}" title="{fmt(d, "%a %#I:%M %p")}">'
             f'{fmt(d, "%a %#I:%M %p")}</time>') if d else ""
        badge = f'<span class="n">{c["n"]} outlets</span>' if c["n"] > 1 else ""
        sec = f'<span class="sec">{escape(TITLES.get(c["section"], c["section"]))}</span>' if show_sec else ""
        summ = lead["summary"]
        if summ.lower().startswith(lead["title"].lower()[:30]):
            summ = ""
        summ = (summ[:260] + "…") if len(summ) > 260 else summ
        p = f"<p>{escape(summ)}</p>" if summ else ""
        tabs = " ".join(sorted(c["tabs"]))
        return (f'<article class="story" data-tabs="{tabs}"><h3>{escape(lead["title"])}</h3>{p}'
                f'<div class="meta">{sec}{badge}{t}</div>'
                f'<div class="src">{"".join(links)}</div></article>')

    def ranked(cs):
        # stories carried by several outlets first, then newest
        return sorted(cs, key=lambda c: (min(c["n"], 3), c["time"]), reverse=True)

    def capped(cs, name):
        out = [story(c) for c in cs[:CAP]]
        if len(cs) > CAP:
            out.append(f'<details><summary>{len(cs) - CAP} more in {escape(name)}</summary>')
            out += [story(c) for c in cs[CAP:]]
            out.append("</details>")
        return out

    # which tabs each story belongs to: its own section, plus Finance for market-moving
    # World/US news (oil, tariffs, the Fed...), plus Top for the most-covered ones
    for c in clusters:
        c["tabs"] = {c["section"].lower()}
        if c["section"] != "Finance" and MARKET_PULL.search(c["lead"]["title"]):
            c["tabs"].add("finance")
    top = sorted([c for c in clusters if c["n"] >= 3], key=lambda c: (-c["n"], c["time"]))[:10]
    for c in top:
        c["tabs"].add("top")

    panels, tabbar, total = [], [], 0
    for sec in TABS:
        sid = sec.lower()
        name = TITLES.get(sec, sec)
        if sec == "Markets":
            tabbar.append('<button data-tab="markets">Markets</button>')
            continue
        if sec == "Top":
            cs = top
            inner = ['<p class="muted lede">Stories carried by 3 or more outlets.</p>']
            inner += [story(c, True) for c in cs]
        elif sec == "Finance":
            cs = [c for c in clusters if "finance" in c["tabs"]]
            inner = []
            for g, rx in FIN_GROUPS:
                gs = ranked([c for c in cs if c.get("fg") is None and (rx is None or rx.search(c["lead"]["title"]))])
                for c in gs:
                    c["fg"] = g
                if gs:
                    inner.append(f'<h3 class="fgroup">{escape(g)}<span class="count">{len(gs)}</span></h3>')
                    inner += capped(gs, g)
        else:
            cs = ranked([c for c in clusters if c["section"] == sec])
            inner = capped(cs, name)
        if not cs:
            continue
        total += len(cs) if sec != "Top" else 0
        tabbar.append(f'<button data-tab="{sid}">{escape(name)}</button>')
        panels.append(f'<section class="panel" data-tab="{sid}" hidden>' + "\n".join(inner) + "</section>")

    # "Latest first" view: every story in one timeline, hour headings; filtered by tab in JS
    latest, last_hour = [], None
    for c in sorted([c for c in clusters if c["time"]], key=lambda c: c["time"], reverse=True):
        d = datetime.fromisoformat(c["time"]).astimezone(CT)
        hour = fmt(d, "%A %#I %p")
        if hour != last_hour:
            latest.append(f'<h4 class="hour">{escape(hour)}</h4>')
            last_hour = hour
        latest.append(story(c, True))

    board = strip = ""
    if not os.environ.get("NEWS_NO_MARKETS"):
        try:
            import markets
            board = markets.board_html()
            strip = markets.strip_html()
        except Exception as e:
            board = f'<div class="board"><p class="muted">Market data unavailable ({escape(str(e))}).</p></div>'

    fetched = datetime.fromisoformat(snap["fetched_at"]).astimezone(CT)
    failed = ", ".join(snap["failed"]) or "none"
    html = TEMPLATE.format(
        when=escape(fmt(fetched, "%A, %B %d · %#I:%M %p CT")),
        total=total, raw=len(snap["items"]), hours=snap["hours"],
        tabbar="".join(tabbar), board=board, strip=strip, panels="\n".join(panels),
        latest="\n".join(latest), hint=HINT, failed=escape(failed),
        board_css=BOARD_CSS)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, "w", encoding="utf-8").write(html)
    print(f"wrote {OUT}: {total} stories from {len(snap['items'])} items")


TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="900">
<title>News</title>
<link rel="apple-touch-icon" href="icon.png">
<meta name="apple-mobile-web-app-title" content="News">
<meta name="apple-mobile-web-app-capable" content="yes">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Source+Serif+4:opsz,wght@8..60,600;8..60,700&family=Source+Sans+3:wght@400;600;700&display=swap" rel="stylesheet">
<style>
:root {{ --bg:#faf8f4; --fg:#1f1d1a; --muted:#6b665e; --line:#e4dfd6; --accent:#2d5a5a;
  --badge:#e2ece9; --link:#2d5a8a; --up:#1d7a3e; --dn:#b3261e;
  --card:#ffffff; --card-b:#eef4f2; --cardline:#d6d0c4; --cardline-b:#b9d0ca; --edge:#2d5a5a; --edge-b:#c0843d; --shadow:0 1px 3px rgba(40,30,20,.08); }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{
  --bg:#17161a; --fg:#e8e4dc; --muted:#9a958c; --line:#2c2a30; --accent:#8cc7c0;
  --badge:#22312f; --link:#8fb6e0; --up:#5fc787; --dn:#ff8a80;
  --card:#211f25; --card-b:#1c2726; --cardline:#3a3740; --cardline-b:#2f4a46; --edge:#8cc7c0; --edge-b:#e0a56f; --shadow:none; }} }}
:root[data-theme="dark"] {{ --bg:#17161a; --fg:#e8e4dc; --muted:#9a958c; --line:#2c2a30;
  --accent:#8cc7c0; --badge:#22312f; --link:#8fb6e0; --up:#5fc787; --dn:#ff8a80;
  --card:#211f25; --card-b:#1c2726; --cardline:#3a3740; --cardline-b:#2f4a46; --edge:#8cc7c0; --edge-b:#e0a56f; --shadow:none; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--fg);
  font:17px/1.55 "Source Sans 3", system-ui, -apple-system, "Segoe UI", sans-serif; }}
.wrap {{ max-width:760px; margin:0 auto; padding:0 16px 80px; }}
header {{ padding:28px 0 8px; }}
h1 {{ margin:0; font:700 32px "Source Serif 4", Georgia, serif; letter-spacing:-.01em; }}
.sub {{ color:var(--muted); font:14px "Source Sans 3", system-ui, sans-serif; margin-top:4px; }}
.bar {{ position:sticky; top:0; z-index:3; background:var(--bg); border-bottom:1px solid var(--line);
  padding:8px 0; }}
.tabs {{ display:flex; gap:6px; overflow-x:auto; scrollbar-width:none; font:14px "Source Sans 3", system-ui, sans-serif; }}
.tabs::-webkit-scrollbar {{ display:none; }}
.tabs button {{ flex:none; font:inherit; padding:6px 12px; border-radius:16px; cursor:pointer;
  border:1px solid var(--line); background:transparent; color:var(--muted); }}
.tabs button.on {{ background:var(--accent); border-color:var(--accent); color:var(--bg); }}
.views {{ display:flex; gap:14px; margin-top:8px; font:13px "Source Sans 3", system-ui, sans-serif; }}
.views button {{ font:inherit; border:0; background:none; padding:2px 0; cursor:pointer; color:var(--muted);
  border-bottom:2px solid transparent; }}
.views button.on {{ color:var(--fg); border-bottom-color:var(--accent); }}
.panel {{ padding-top:10px; }}
h3.fgroup {{ font:600 15px "Source Sans 3", system-ui, sans-serif; color:var(--accent); margin:26px 0 0;
  padding-bottom:4px; border-bottom:2px solid var(--accent); }}
h4.group {{ font:600 13px "Source Sans 3", system-ui, sans-serif; text-transform:uppercase; letter-spacing:.06em;
  color:var(--muted); margin:18px 0 2px; }}
.count {{ font:13px "Source Sans 3", system-ui, sans-serif; color:var(--muted); margin-left:10px; font-weight:400; }}
.lede {{ font:14px "Source Sans 3", system-ui, sans-serif; margin:10px 0 0; }}
.story {{ background:var(--card); border:1px solid var(--cardline); border-radius:6px;
  padding:14px 16px 12px; margin:10px 0; }}
.story.alt {{ background:var(--card-b); border-color:var(--cardline-b); }}
.story h3 {{ font:700 19px/1.3 "Source Serif 4", Georgia, serif; margin:0 0 4px; }}
.story p {{ margin:0 0 8px; font-size:16px; color:var(--fg); opacity:.85; }}
.src {{ display:flex; flex-wrap:wrap; gap:6px; margin-top:8px; }}
.src a {{ font:600 12px "Source Sans 3", system-ui, sans-serif; color:var(--link); text-decoration:none;
  border:1px solid var(--line); border-radius:999px; padding:2px 10px; background:var(--bg); }}
.src a:hover {{ border-color:var(--link); }}
.meta {{ font:13px "Source Sans 3", system-ui, sans-serif; color:var(--muted); display:flex; flex-wrap:wrap; gap:4px 12px; align-items:center; }}
time {{ color:var(--muted); }}
.n, .sec {{ background:var(--badge); color:var(--accent); padding:1px 8px; border-radius:999px; font-weight:700; font-size:11px; }}
h4.hour {{ font:600 13px "Source Sans 3", system-ui, sans-serif; text-transform:uppercase; letter-spacing:.06em;
  color:var(--accent); margin:22px 0 0; padding-bottom:4px; border-bottom:1px solid var(--line); }}
details {{ margin-top:8px; }}
summary {{ cursor:pointer; color:var(--link); font:14px "Source Sans 3", system-ui, sans-serif; padding:10px 0; }}
.boardcard {{ background:var(--card); border-radius:12px; padding:4px 14px 10px; margin-top:14px;
  box-shadow:var(--shadow); }}
footer {{ margin-top:36px; color:var(--muted); font:13px/1.5 "Source Sans 3", system-ui, sans-serif; }}
{board_css}
</style>
</head>
<body><div class="wrap">
<header><h1>News</h1>
<div class="sub">{when} · {total} stories (from {raw} items, last {hours}h) · no AI, auto-built<br>{hint}</div></header>
<div class="bar">
  <div class="tabs">{tabbar}</div>
  <div class="views"><button data-view="topic">By topic</button><button data-view="latest">Latest first</button></div>
</div>
<div id="strip" hidden>{strip}</div>
<div id="board" class="boardcard" hidden>{board}</div>
<div id="v-topic">
{panels}
</div>
<div id="v-latest" hidden>
{latest}
</div>
<footer>Built by script only: headlines are grouped by word overlap and ranked by how many outlets
carry them. Summaries are the outlets' own feed text. Page reloads itself every 15 minutes.
Feeds that failed: {failed}.</footer>
</div>
<script>
const st = {{ tab: "finance", view: "topic" }};
try {{ Object.assign(st, JSON.parse(localStorage.getItem("newsState") || "{{}}")); }} catch (e) {{}}
const tabs = [...document.querySelectorAll(".tabs button")];
if (!tabs.some(b => b.dataset.tab === st.tab)) st.tab = tabs[0].dataset.tab;
function render() {{
  tabs.forEach(b => b.classList.toggle("on", b.dataset.tab === st.tab));
  document.querySelectorAll(".views button").forEach(b => b.classList.toggle("on", b.dataset.view === st.view));
  const mk = st.tab === "markets";
  document.getElementById("strip").hidden = st.tab !== "finance";
  document.getElementById("board").hidden = !mk;
  document.querySelector(".views").style.display = mk ? "none" : "";
  document.getElementById("v-topic").hidden = mk || st.view !== "topic";
  document.getElementById("v-latest").hidden = mk || st.view !== "latest";
  document.querySelectorAll(".panel").forEach(p => p.hidden = p.dataset.tab !== st.tab);
  if (st.view === "latest") {{
    let head = null, any = false;
    const close = () => {{ if (head) head.hidden = !any; }};
    for (const el of document.getElementById("v-latest").children) {{
      if (el.tagName === "H4") {{ close(); head = el; any = false; continue; }}
      const show = el.dataset.tabs.split(" ").includes(st.tab);
      el.hidden = !show; any = any || show;
    }}
    close();
  }}
  // format A / B: alternate among the cards actually on screen, per block
  const root = st.view === "latest" ? [document.getElementById("v-latest")]
             : [...document.querySelectorAll(".panel")].filter(p => !p.hidden);
  root.forEach(r => {{
    let i = 0;
    r.querySelectorAll("article.story").forEach(a => {{
      if (a.hidden) return;
      if (a.previousElementSibling && /^H[34]$/.test(a.previousElementSibling.tagName) && !a.closest("#v-latest")) i = 0;
      a.classList.toggle("alt", i++ % 2 === 1);
    }});
  }});
  try {{ localStorage.setItem("newsState", JSON.stringify(st)); }} catch (e) {{}}
}}
function ago() {{
  const now = Date.now();
  document.querySelectorAll("time[datetime]").forEach(t => {{
    const m = Math.round((now - Date.parse(t.getAttribute("datetime"))) / 60000);
    t.textContent = m < 1 ? "just now" : m < 60 ? m + " min ago"
      : m < 24 * 60 ? Math.round(m / 60) + " h ago" : t.title;
  }});
}}
ago(); setInterval(ago, 60000);
tabs.forEach(b => b.onclick = () => {{ st.tab = b.dataset.tab; render(); window.scrollTo(0, 0); }});
document.querySelectorAll("[data-goto]").forEach(b => b.onclick = () => {{ st.tab = b.dataset.goto; render(); window.scrollTo(0, 0); }});
document.querySelectorAll(".views button").forEach(b => b.onclick = () => {{ st.view = b.dataset.view; render(); }});
render();
</script>
</body></html>
"""

if __name__ == "__main__":
    main()
