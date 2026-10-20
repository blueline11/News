#!/usr/bin/env python3
"""Script-only news page (no AI): fetch feeds, merge look-alike headlines,
rank by how many outlets carry a story, write ../News-Raw.html.

Usage:  python raw.py            (fetches first, then renders)
        python raw.py --no-fetch (render from the existing snapshot.json)
Meant to run unattended from Windows Task Scheduler.
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
OUT = os.environ.get("NEWS_OUT") or os.path.join(os.path.dirname(BASE), "News-Raw.html")
try:
    from zoneinfo import ZoneInfo
    CT = ZoneInfo("America/Chicago")  # handles daylight saving
except Exception:
    CT = timezone(timedelta(hours=-6))
# how-to-refresh line under the title; the web copy sets its own
HINT = os.environ.get("NEWS_HINT",
                      "To refresh: double-click <b>Update-News.bat</b> in the News folder.")
CAP = 20
SECTIONS = ["World", "US", "Texas", "Economy", "Tech", "Science", "Turkiye", "Culture", "Sports"]
TITLES = {"Texas": "Texas & Austin", "Tech": "Tech", "Science": "Science & Health",
          "Turkiye": "Türkiye"}

# headlines that are never news
JUNK = re.compile(
    r"obituary|realtor\.com|scores, news & stats|^\S+ - spectrum news|tierra's texas|"
    r"specimen tree delivery|tickets to this weekend|who am i\?|today's other quizzes|"
    r"gossip|ratings$|team of the week|photo highlights|\.jpg|announces?|introduces|"
    r"launches online|co-marketing|partnership to advance|world's smallest|"
    r"the afp top 10|afp recognizes|^watch:|all the goals|best plays|morning news brief|"
    r"morning bid|commentary:|press review", re.I)

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
TX = re.compile(r"\b(texas|austin|travis|abbott|paxton|houston|dallas|san antonio|"
                r"round rock|cota|longhorns|ut |hays|williamson|txdot|ercot)\b", re.I)


def resection(it, t):
    sec = it["section"]
    if it["source"] == "Austin local" and not TX.search(t):
        return None  # wire copy republished by a local site; it is covered elsewhere
    if sec in ("World", "US"):
        if SPORT.search(t):
            return "Sports"
        if ECON.search(t):
            return "Economy"
    return sec


def fmt(d, f):
    """strftime with %#I = hour without leading zero, on Windows and Linux alike."""
    return d.strftime(f.replace("%#I", str(int(d.strftime("%I")))))


def clean_title(it):
    t = it["title"]
    if it["outlet"]:  # Google News appends " - Outlet"
        t = re.sub(r"\s+-\s+[^-]+$", "", t)
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
    if s.startswith(("Reuters", "AP", "AFP")) and it["outlet"]:
        base = s.split(" ")[0]
        o = it["outlet"]
        return base if o.lower().startswith((base.lower(), "afp.com", "ap news")) else o
    if s == "Austin local":
        return it["outlet"] or "Local"
    return {"SCMP Asia": "SCMP"}.get(s, s)


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
        t = datetime.fromisoformat(c["time"]).astimezone(CT) if c["time"] else None
        t = fmt(t, "%a %#I:%M %p") if t else ""
        badge = f'<span class="n">{c["n"]} outlets</span>' if c["n"] > 1 else ""
        sec = f'<span class="sec">{escape(TITLES.get(c["section"], c["section"]))}</span>' if show_sec else ""
        summ = lead["summary"]
        if summ.lower().startswith(lead["title"].lower()[:30]):
            summ = ""
        summ = (summ[:260] + "…") if len(summ) > 260 else summ
        p = f"<p>{escape(summ)}</p>" if summ else ""
        return (f'<article class="story"><h3>{escape(lead["title"])}</h3>{p}'
                f'<div class="meta">{sec}{badge}<span>{t}</span>'
                f'<span class="src">{" · ".join(links)}</span></div></article>')

    top = sorted([c for c in clusters if c["n"] >= 3], key=lambda c: (-c["n"], c["time"]))[:10]
    top_ids = {id(c) for c in top}

    nav = ['<a href="#most-covered">Most covered</a>']
    body = ['<section id="most-covered"><h2>Most covered<span class="count">stories carried by 3+ outlets</span></h2>']
    body += [story(c, True) for c in top]
    body.append("</section>")
    total = len(top)
    for sec in SECTIONS:
        cs = [c for c in clusters if c["section"] == sec and id(c) not in top_ids]
        cs.sort(key=lambda c: (-min(c["n"], 3), c["time"]), reverse=False)
        cs.sort(key=lambda c: c["time"], reverse=True)
        cs.sort(key=lambda c: min(c["n"], 3), reverse=True)  # multi-outlet first, then newest
        if not cs:
            continue
        name = TITLES.get(sec, sec)
        sid = sec.lower()
        nav.append(f'<a href="#{sid}">{escape(name)}</a>')
        body.append(f'<section id="{sid}"><h2>{escape(name)}<span class="count">{len(cs)}</span></h2>')
        body += [story(c) for c in cs[:CAP]]
        if len(cs) > CAP:
            body.append(f'<details><summary>{len(cs) - CAP} more in {escape(name)}</summary>')
            body += [story(c) for c in cs[CAP:]]
            body.append("</details>")
        body.append("</section>")
        total += len(cs)

    # "Latest first" view: every story in one timeline, hour headings
    latest, last_hour = [], None
    for c in sorted([c for c in clusters if c["time"]], key=lambda c: c["time"], reverse=True):
        d = datetime.fromisoformat(c["time"]).astimezone(CT)
        hour = fmt(d, "%A %#I %p")
        if hour != last_hour:
            latest.append(f'<h4 class="hour">{escape(hour)}</h4>')
            last_hour = hour
        latest.append(story(c, True))

    fetched = datetime.fromisoformat(snap["fetched_at"]).astimezone(CT)
    failed = ", ".join(snap["failed"]) or "none"
    html = TEMPLATE.format(
        when=escape(fmt(fetched, "%A, %B %d · %#I:%M %p CT")),
        total=total, raw=len(snap["items"]), hours=snap["hours"],
        nav="".join(nav), body="\n".join(body), latest="\n".join(latest), hint=HINT, failed=escape(failed))
    open(OUT, "w", encoding="utf-8").write(html)
    print(f"wrote {OUT}: {total} stories from {len(snap['items'])} items")


TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="900">
<title>News Raw</title>
<link rel="apple-touch-icon" href="icon.png">
<meta name="apple-mobile-web-app-title" content="News">
<meta name="apple-mobile-web-app-capable" content="yes">
<style>
:root {{ --bg:#faf8f4; --fg:#1f1d1a; --muted:#6b665e; --line:#e4dfd6; --accent:#2d5a5a;
  --badge:#e2ece9; --link:#2d5a8a; }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{
  --bg:#17161a; --fg:#e8e4dc; --muted:#9a958c; --line:#2c2a30; --accent:#8cc7c0;
  --badge:#22312f; --link:#8fb6e0; }} }}
:root[data-theme="dark"] {{ --bg:#17161a; --fg:#e8e4dc; --muted:#9a958c; --line:#2c2a30;
  --accent:#8cc7c0; --badge:#22312f; --link:#8fb6e0; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--fg);
  font:17px/1.55 Georgia, "Times New Roman", serif; }}
.wrap {{ max-width:760px; margin:0 auto; padding:0 16px 80px; }}
header {{ padding:32px 0 10px; border-bottom:1px solid var(--line); }}
h1 {{ margin:0; font-size:28px; }}
.sub {{ color:var(--muted); font:14px system-ui, sans-serif; margin-top:4px; }}
nav {{ position:sticky; top:0; background:var(--bg); border-bottom:1px solid var(--line);
  padding:10px 0; display:flex; flex-wrap:wrap; gap:6px 16px; font:14px system-ui, sans-serif; z-index:2; }}
nav a {{ color:var(--muted); text-decoration:none; }}
section {{ padding-top:26px; scroll-margin-top:48px; }}
h2 {{ font-size:21px; margin:0 0 4px; color:var(--accent); border-bottom:2px solid var(--accent); padding-bottom:4px; }}
.count {{ font:13px system-ui, sans-serif; color:var(--muted); margin-left:10px; }}
.story {{ padding:11px 0; border-bottom:1px solid var(--line); }}
.story h3 {{ font-size:18px; margin:0 0 3px; line-height:1.35; }}
.story p {{ margin:0 0 5px; font-size:16px; }}
.meta {{ font:13px system-ui, sans-serif; color:var(--muted); display:flex; flex-wrap:wrap; gap:4px 12px; align-items:center; }}
.meta a {{ color:var(--link); text-decoration:none; }}
.n, .sec {{ background:var(--badge); color:var(--accent); padding:1px 6px; border-radius:3px; font-weight:600; font-size:11px; }}
.views {{ display:flex; gap:8px; padding:14px 0 4px; font:14px system-ui, sans-serif; }}
.views button {{ font:inherit; padding:6px 14px; border-radius:16px; cursor:pointer;
  border:1px solid var(--line); background:transparent; color:var(--muted); }}
.views button.on {{ background:var(--accent); border-color:var(--accent); color:var(--bg); }}
h4.hour {{ font:600 13px system-ui, sans-serif; text-transform:uppercase; letter-spacing:.06em;
  color:var(--accent); margin:22px 0 0; padding-bottom:4px; border-bottom:1px solid var(--line);
  position:sticky; top:0; background:var(--bg); }}
details {{ margin-top:8px; }}
summary {{ cursor:pointer; color:var(--link); font:14px system-ui, sans-serif; padding:10px 0; }}
footer {{ margin-top:36px; color:var(--muted); font:13px/1.5 system-ui, sans-serif; }}
</style>
</head>
<body><div class="wrap">
<header><h1>News — raw</h1>
<div class="sub">{when} · {total} stories (from {raw} items, last {hours}h) · no AI, auto-built<br>{hint}</div></header>
<div class="views" role="tablist">
  <button id="b-topic" class="on" onclick="show('topic')">By topic</button>
  <button id="b-latest" onclick="show('latest')">Latest first</button>
</div>
<div id="v-topic">
<nav>{nav}</nav>
{body}
</div>
<div id="v-latest" hidden>
{latest}
</div>
<footer>Built by script only: headlines are grouped by word overlap and ranked by how many outlets
carry them. Summaries are the outlets' own feed text. Page reloads itself every 15 minutes.
Feeds that failed: {failed}.</footer>
</div>
<script>
function show(v) {{
  for (const k of ["topic", "latest"]) {{
    document.getElementById("v-" + k).hidden = k !== v;
    document.getElementById("b-" + k).classList.toggle("on", k === v);
  }}
  try {{ localStorage.setItem("newsView", v); }} catch (e) {{}}
}}
try {{ const v = localStorage.getItem("newsView"); if (v) show(v); }} catch (e) {{}}
</script>
</body></html>
"""

if __name__ == "__main__":
    main()
