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


MEDIA = "{http://search.yahoo.com/mrss/}"
CONTENT = "{http://purl.org/rss/1.0/modules/content/}encoded"
IMG_SRC = re.compile(r"""<img[^>]+src=["']([^"']+)""", re.I)
NOT_PHOTO = re.compile(r"pixel|spacer|feedburner|doubleclick|gravatar|/ads?/|logo|\.gif(\?|$)", re.I)


def find_image(it, *html):
    """Picture the outlet attached to the item: media:thumbnail/content, enclosure, or the first <img> in the body."""
    cands = []
    for el in it.iter():
        tag = el.tag if isinstance(el.tag, str) else ""
        url = el.get("url") or ""
        if tag in (MEDIA + "thumbnail", MEDIA + "content") or tag.endswith("}enclosure") or tag == "enclosure":
            typ, medium = el.get("type") or "", el.get("medium") or ""
            if tag.endswith("enclosure") and not typ.startswith("image"):
                continue
            if tag == MEDIA + "content" and not (medium == "image" or typ.startswith("image")
                                                 or re.search(r"\.(jpe?g|png|webp)(\?|$)", url, re.I)):
                continue
            w = el.get("width")
            if w and w.isdigit() and int(w) < 100:
                continue
            cands.append((int(w) if w and w.isdigit() else 0, url))
        elif tag == "image" and (el.text or "").strip().startswith("http"):  # CBS: <image>url</image>
            cands.append((0, el.text.strip()))
        elif tag.endswith("}link") and el.get("rel") == "enclosure" and (el.get("type") or "").startswith("image"):
            cands.append((0, el.get("href") or ""))
    # largest declared size wins; an undeclared size keeps feed order
    cands.sort(key=lambda c: -c[0])
    urls = [u for _, u in cands]
    for h in html:
        urls += IMG_SRC.findall(unescape(h or ""))
    for u in urls:
        u = unescape(u).strip()
        if u.startswith("//"):
            u = "https:" + u
        if u.startswith("http://"):
            u = "https://" + u[7:]  # the page is https; plain http images would be blocked
        if u.startswith("https://") and not NOT_PHOTO.search(u):
            return u
    return ""


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
            "image": "" if src_el is not None else find_image(it, t("description"), it.findtext(CONTENT)),
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
            "image": find_image(it, it.findtext(ns + "summary"), it.findtext(ns + "content")),
        })
    return out


def main():
    with open(SRC, encoding="utf-8") as f:
        cfg = json.load(f)

    # (name, section, url, hours): "hours" in sources.json widens the window for slow publishers
    feeds = [(s["name"], s["section"], s["url"], s.get("hours", HOURS)) for s in cfg.get("rss", [])]
    for s in cfg.get("google_news", []):
        ed = "&hl=tr&gl=TR&ceid=TR:tr" if s.get("lang") == "tr" else "&hl=en-US&gl=US&ceid=US:en"
        url = "https://news.google.com/rss/search?q=" + urllib.parse.quote(s["q"]) + ed
        feeds.append((s["name"], s["section"], url, s.get("hours", HOURS)))

    now = datetime.now(timezone.utc)
    seen, items, errors = set(), [], []
    for name, section, url, hours in feeds:
        cutoff = now - timedelta(hours=hours)
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
