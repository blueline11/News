#!/usr/bin/env python3
"""Radar tab: a price row and the latest news for each symbol in radar.txt.

News comes from Yahoo Finance's per-symbol headline feeds (covers small caps and their
press releases); prices from the same chart endpoint as the market board.
"""
import json
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import escape, unescape
import xml.etree.ElementTree as ET

import markets

BASE = os.path.dirname(os.path.abspath(__file__))
DAYS = 7          # news window
PER_SYMBOL = 6    # newest N per symbol, so one chatty name can't flood the list

# template filler that adds nothing
FLUFF = re.compile(
    r"surpasses market returns|some facts worth knowing|key facts|what you should know|"
    r"should you (buy|sell)|is it time to|here's why|stock sinks as market gains|"
    r"what does .{0,40} offer that|top-ranked|strong buy|zacks rank|bull of the day|"
    r"bear of the day|in focus|trending stock|soars?: is it|plunges?: is it", re.I)


def symbols():
    with open(os.path.join(BASE, "radar.txt"), encoding="utf-8") as f:
        return [s.strip().upper() for s in f.read().replace(",", " ").split() if s.strip()]


def news(sym):
    url = ("https://feeds.finance.yahoo.com/rss/2.0/headline?s=" + urllib.parse.quote(sym) +
           "&region=US&lang=en-US")
    req = urllib.request.Request(url, headers={"User-Agent": markets.UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        root = ET.fromstring(r.read())
    out = []
    for it in root.iter("item"):
        title = unescape((it.findtext("title") or "").strip())
        try:
            d = parsedate_to_datetime(it.findtext("pubDate")).astimezone(timezone.utc)
        except Exception:
            continue
        desc = re.sub(r"<[^>]+>", " ", it.findtext("description") or "")
        desc = re.sub(r"\s+", " ", unescape(desc)).strip()
        out.append({"sym": sym, "title": title, "url": (it.findtext("link") or "").strip(),
                    "time": d, "summary": desc})
    return out


def quote(sym):
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/" + urllib.parse.quote(sym) +
           "?range=3mo&interval=1d")
    req = urllib.request.Request(url, headers={"User-Agent": markets.UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        meta = json.load(r)["chart"]["result"][0]["meta"]
    name = meta.get("shortName") or meta.get("longName") or sym
    price, hist = markets.fetch(sym)
    return name, price, hist


def short_name(n):
    n = re.sub(r",?\s+(Inc\.?|Corp(oration)?\.?|Ltd\.?|Holdings?|Technologies|Technology|Co\.?|"
               r"Company|Group|plc|N\.V\.|S\.A\.|Incorporated|Limited)\b\.?", "", n, flags=re.I)
    return n.strip(" ,.") or n


def build(fmt, CT):
    """Return (html, count). fmt/CT come from raw.py so times match the rest of the page."""
    syms = symbols()
    cutoff = datetime.now(timezone.utc) - timedelta(days=DAYS)
    rows, items, seen = [], [], set()
    for sym in syms:
        keys = [sym]
        try:
            name, price, hist = quote(sym)
            first = re.split(r"[\s,.]+", short_name(name))[0]
            if len(first) >= 4:
                keys.append(first)  # "Amkor", "GlobalFoundries", "Akamai"...
            d1 = markets.change(price, hist[-1] if hist else None, "pct")
            m1 = markets.change(price, hist[-21] if len(hist) >= 21 else None, "pct")
            rows.append((d1 or 0, f'<tr><td class="nm"><b>{sym}</b> <span class="muted">{escape(short_name(name))}</span></td>'
                                  f'<td class="px">{markets.fmt_price(price, "pct")}</td>'
                                  f'{markets.cell(d1, "pct")}{markets.cell(m1, "pct")}'
                                  f'<td class="sp">{markets.spark(hist + [price])}</td></tr>'))
        except Exception:
            pass
        try:
            # Yahoo's per-symbol feed also carries loosely related pieces; keep ones that name the company
            mention = re.compile(r"\b(" + "|".join(re.escape(k) for k in keys) + r")\b", re.I)
            got = [n for n in news(sym) if n["time"] >= cutoff and not FLUFF.search(n["title"])
                   and mention.search(n["title"] + " " + n["summary"])]
        except Exception:
            got = []
        got.sort(key=lambda n: n["time"], reverse=True)
        for n in got[:PER_SYMBOL]:
            key = re.sub(r"\W+", "", n["title"].lower())[:80]
            if key in seen:
                continue
            seen.add(key)
            items.append(n)

    items.sort(key=lambda n: n["time"], reverse=True)
    out = []
    if rows:
        rows.sort(key=lambda r: -r[0])
        out.append('<div class="boardcard"><div class="board"><h4 class="group">Today'
                   '<span class="muted"> · sorted by today</span></h4><table class="mk">'
                   '<colgroup><col><col class="c-px"><col class="c-ch"><col class="c-ch"><col class="c-sp"></colgroup>'
                   '<tr><th></th><th>Price</th><th>Day</th><th>Month</th><th></th></tr>')
        out += [r for _, r in rows]
        out.append("</table></div></div>")
    out.append(f'<h3 class="fgroup">Latest news<span class="count">{len(items)} · last {DAYS} days</span></h3>')
    for n in items:
        d = n["time"].astimezone(CT)
        summ = n["summary"]
        if summ.lower().startswith(n["title"].lower()[:30]):
            summ = ""
        summ = (summ[:240] + "…") if len(summ) > 240 else summ
        p = f"<p>{escape(summ)}</p>" if summ else ""
        out.append(f'<article class="story" data-tabs="radar"><h3>{escape(n["title"])}</h3>{p}'
                   f'<div class="meta"><span class="sec">{n["sym"]}</span>'
                   f'<time datetime="{d.isoformat()}" title="{fmt(d, "%a %#I:%M %p")}">{fmt(d, "%a %#I:%M %p")}</time></div>'
                   f'<div class="src"><a href="{escape(n["url"])}" target="_blank" rel="noopener">Yahoo Finance</a></div></article>')
    if not items:
        out.append('<p class="muted lede">No news in the last week.</p>')
    return "\n".join(out), len(items)
