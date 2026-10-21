#!/usr/bin/env python3
"""World news feed fetcher (mechanical layer for News-Feed.html).

Reads sources.json, pulls every RSS feed and Google News site: search, keeps
items from the last HOURS hours, dedups by URL, and writes snapshot.json
(overwritten each run). stdlib only -- no pip deps.

Usage:  python fetch-feeds.py [hours]     (default 30)
"""
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from html import unescape

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, "sources.json")
OUT = os.path.join(BASE, "snapshot.json")
HOURS = int(sys.argv[1]) if len(sys.argv) > 1 else 30

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")


def fetch(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
        "Accept-Language": "en,en-US;q=0.9",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = r.read()
    except urllib.error.HTTPError as e:
        if e.code not in (401, 403, 429):
            raise
        data = b""  # blocked for Python (Arab News): retry with curl below
    if data.strip():
        return data
    # some sites (PBS, ESPN) answer Python with an empty 202; Windows' curl gets through
    return subprocess.run(["curl", "-s", "-L", "--max-time", "30", "-A", "Mozilla/5.0", url],
                          capture_output=True, check=True).stdout


def strip_html(s):
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"\s+", " ", s)
    return unescape(s).strip()


def parse_date(s):
    if not s:
        return None
    s = unescape(s).strip()  # Sözcü writes "+0300" as "&#x2B;0300"
    try:
        d = parsedate_to_datetime(s)
    except Exception:
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def parse_feed(data):
    root = ET.fromstring(data)
    dc = "{http://purl.org/dc/elements/1.1/}"
    out = []
    # RSS 2.0 and RSS 1.0 (RDF, used by DW) items
    for it in list(root.iter("item")) + list(root.iter("{http://purl.org/rss/1.0/}item")):
        def t(tag):
            v = it.findtext(tag)
            if v is None:
                v = it.findtext("{http://purl.org/rss/1.0/}" + tag)
            return v
        src_el = it.find("source")  # Google News: original outlet
        out.append({
            "title": strip_html(t("title")),
            "url": (t("link") or "").strip(),
            "published": t("pubDate") or it.findtext(dc + "date"),
            "summary": strip_html(t("description"))[:700],
            "outlet": src_el.text.strip() if src_el is not None and src_el.text else "",
        })
    ns = "{http://www.w3.org/2005/Atom}"
    for it in root.iter(ns + "entry"):
        link_el = it.find(ns + "link")
        out.append({
            "title": strip_html(it.findtext(ns + "title")),
            "url": link_el.get("href") if link_el is not None else "",
            "published": it.findtext(ns + "published") or it.findtext(ns + "updated"),
            "summary": strip_html(it.findtext(ns + "summary"))[:700],
            "outlet": "",
        })
    return out


def main():
    with open(SRC, encoding="utf-8") as f:
        cfg = json.load(f)

    feeds = [(s["name"], s["section"], s["url"]) for s in cfg.get("rss", [])]
    for s in cfg.get("google_news", []):
        ed = "&hl=tr&gl=TR&ceid=TR:tr" if s.get("lang") == "tr" else "&hl=en-US&gl=US&ceid=US:en"
        url = "https://news.google.com/rss/search?q=" + urllib.parse.quote(s["q"]) + ed
        feeds.append((s["name"], s["section"], url))

    cutoff = datetime.now(timezone.utc) - timedelta(hours=HOURS)
    seen, items, errors = set(), [], []
    for name, section, url in feeds:
        try:
            raw = parse_feed(fetch(url))
            kept = 0
            for it in raw:
                d = parse_date(it["published"])
                if d and d < cutoff:
                    continue
                if not it["url"] or it["url"] in seen or not it["title"]:
                    continue
                seen.add(it["url"])
                it["published"] = d.isoformat() if d else ""
                it["source"] = name
                it["section"] = section
                items.append(it)
                kept += 1
            print(f"OK   {name}: {len(raw)} items, {kept} in window")
        except Exception as e:
            errors.append(name)
            print(f"FAIL {name}: {e}")

    items.sort(key=lambda x: x["published"], reverse=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"fetched_at": datetime.now(timezone.utc).isoformat(),
                   "hours": HOURS, "failed": errors, "items": items},
                  f, ensure_ascii=False, indent=0)
    print(f"\n{len(items)} items -> snapshot.json. {len(errors)} feeds failed.")


if __name__ == "__main__":
    main()
