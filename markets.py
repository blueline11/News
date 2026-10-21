#!/usr/bin/env python3
"""Market board for the Finance tab: indexes, rates, commodities, sectors.

Daily closes come from Yahoo Finance's public chart endpoint (no key; quotes may be
delayed). board_html() returns a self-contained HTML block; on any failure a row is
simply left out, and if everything fails the board says so instead of breaking the page.
"""
import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html import escape

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"

# (group, symbol, label, kind)  kind: "pct" = % change, "yield" = change in basis points
BOARD = [
    ("Indexes", "SPY", "S&P 500 (SPY)", "pct"),
    ("Indexes", "QQQ", "Nasdaq 100 (QQQ)", "pct"),
    ("Indexes", "DIA", "Dow (DIA)", "pct"),
    ("Indexes", "IWM", "Small caps (IWM)", "pct"),
    ("Rates & risk", "^TNX", "10-yr Treasury yield", "yield"),
    ("Rates & risk", "^VIX", "VIX (fear gauge)", "pct"),
    ("Rates & risk", "DX-Y.NYB", "US dollar index", "pct"),
    ("Commodities", "USO", "Oil (USO)", "pct"),
    ("Commodities", "BNO", "Brent oil (BNO)", "pct"),
    ("Commodities", "UNG", "Natural gas (UNG)", "pct"),
    ("Commodities", "GLD", "Gold (GLD)", "pct"),
    ("Commodities", "SLV", "Silver (SLV)", "pct"),
    ("Commodities", "CPER", "Copper (CPER)", "pct"),
    ("Sectors", "XLK", "Technology", "pct"),
    ("Sectors", "SMH", "Semiconductors", "pct"),
    ("Sectors", "XLC", "Communication", "pct"),
    ("Sectors", "XLY", "Consumer discretionary", "pct"),
    ("Sectors", "XLP", "Consumer staples", "pct"),
    ("Sectors", "XLF", "Financials", "pct"),
    ("Sectors", "XLV", "Health care", "pct"),
    ("Sectors", "XLI", "Industrials", "pct"),
    ("Sectors", "XLE", "Energy", "pct"),
    ("Sectors", "XLB", "Materials", "pct"),
    ("Sectors", "XLU", "Utilities", "pct"),
    ("Sectors", "XLRE", "Real estate", "pct"),
    ("Crypto", "BTC-USD", "Bitcoin", "pct"),
]


def fetch(symbol):
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/" +
           urllib.parse.quote(symbol) + "?range=3mo&interval=1d")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        res = json.load(r)["chart"]["result"][0]
    meta = res["meta"]
    pts = [(t, c) for t, c in zip(res["timestamp"], res["indicators"]["quote"][0]["close"]) if c is not None]
    price = meta.get("regularMarketPrice") or pts[-1][1]
    # if the last bar is today's (still forming) bar, the previous close is the bar before it
    last_day = datetime.fromtimestamp(pts[-1][0], timezone.utc).date()
    mkt_day = datetime.fromtimestamp(meta.get("regularMarketTime", pts[-1][0]), timezone.utc).date()
    closes = [c for _, c in pts]
    hist = closes[:-1] if last_day == mkt_day else closes
    return price, hist


def change(price, past, kind):
    if not past:
        return None
    return (price - past) * 100 if kind == "yield" else (price / past - 1) * 100


def cell(v, kind):
    if v is None:
        return '<td class="ch">–</td>'
    cls = "up" if v > 0 else "dn" if v < 0 else ""
    txt = f"{v:+.0f} bp" if kind == "yield" else f"{v:+.1f}%"
    return f'<td class="ch {cls}">{txt}</td>'


def spark(series):
    s = series[-22:]
    if len(s) < 2:
        return ""
    lo, hi = min(s), max(s)
    rng = (hi - lo) or 1
    w, h = 80, 22
    pts = " ".join(f"{i * w / (len(s) - 1):.1f},{h - (v - lo) / rng * h:.1f}" for i, v in enumerate(s))
    cls = "up" if s[-1] >= s[0] else "dn"
    return f'<svg class="spark {cls}" viewBox="0 -1 {w} {h + 2}" preserveAspectRatio="none"><polyline points="{pts}"/></svg>'


def fmt_price(p, kind):
    if kind == "yield":
        return f"{p:.2f}%"
    return f"{p:,.0f}" if p >= 10000 else f"{p:,.2f}"


# the compact strip on the Finance tab: (symbol, short label)
STRIP = [("SPY", "S&P 500"), ("QQQ", "Nasdaq"), ("IWM", "Small caps"), ("^TNX", "10-yr"),
         ("^VIX", "VIX"), ("USO", "Oil"), ("GLD", "Gold"), ("BTC-USD", "Bitcoin")]
_seen = {}  # symbol -> (price, day change, kind), filled by board_html()


def strip_html():
    tiles = []
    for sym, short in STRIP:
        if sym not in _seen:
            continue
        price, d1, kind = _seen[sym]
        cls = "up" if (d1 or 0) > 0 else "dn" if (d1 or 0) < 0 else ""
        ch = "–" if d1 is None else (f"{d1:+.0f} bp" if kind == "yield" else f"{d1:+.1f}%")
        tiles.append(f'<div class="tile"><span class="tl">{escape(short)}</span>'
                     f'<span class="tp">{fmt_price(price, kind)}</span><span class="tc {cls}">{ch}</span></div>')
    if not tiles:
        return ""
    return ('<div class="strip">' + "".join(tiles) +
            '<button class="more" data-goto="markets">All markets ›</button></div>')


def board_html():
    rows, ok = {}, 0
    for group, sym, label, kind in BOARD:
        try:
            price, hist = fetch(sym)
            ok += 1
        except Exception:
            continue
        d1 = change(price, hist[-1] if hist else None, kind)
        _seen[sym] = (price, d1, kind)
        w1 = change(price, hist[-5] if len(hist) >= 5 else None, kind)
        m1 = change(price, hist[-21] if len(hist) >= 21 else None, kind)
        rows.setdefault(group, []).append((d1 if d1 is not None else 0, (
            f'<tr><td class="nm">{escape(label)}</td><td class="px">{fmt_price(price, kind)}</td>'
            f'{cell(d1, kind)}{cell(w1, kind).replace("ch", "ch wk", 1)}{cell(m1, kind)}'
            f'<td class="sp">{spark(hist + [price])}</td></tr>')))
    if not ok:
        return '<div class="board"><p class="muted">Market data unavailable this run.</p></div>'
    out = ['<div class="board">']
    for group in dict.fromkeys(g for g, *_ in BOARD):
        if group not in rows:
            continue
        rs = rows[group]
        note = ""
        if group == "Sectors":  # leaders on top
            rs = sorted(rs, key=lambda r: -r[0])
            note = '<span class="muted"> · sorted by today</span>'
        out.append(f'<h4 class="group">{group}{note}</h4><table class="mk">'
                   '<colgroup><col><col class="c-px"><col class="c-ch"><col class="c-ch wk"><col class="c-ch"><col class="c-sp"></colgroup>'
                   '<tr><th></th><th>Price</th><th>Day</th><th class="wk">Week</th><th>Month</th><th></th></tr>')
        out.extend(r for _, r in rs)
        out.append("</table>")
    out.append('<p class="muted small">Prices from Yahoo Finance, may be delayed ~15 min. '
               'Week/month = change vs. 5 and 21 trading days ago. Line = last month.</p></div>')
    return "\n".join(out)


BOARD_CSS = """
.board { margin-top:6px; }
table.mk { width:100%; border-collapse:collapse; table-layout:fixed; font:14px system-ui, sans-serif; }
col.c-px { width:84px; } col.c-ch { width:72px; } col.c-sp { width:92px; }
table.mk th { text-align:right; font-weight:500; color:var(--muted); font-size:12px; padding:4px 6px; }
table.mk td { padding:5px 6px; border-bottom:1px solid var(--line); text-align:right; white-space:nowrap; }
table.mk td.nm { text-align:left; white-space:normal; }
table.mk td.px { font-variant-numeric:tabular-nums; }
td.ch { font-variant-numeric:tabular-nums; }
.up { color:var(--up); } .dn { color:var(--dn); }
td.sp { width:84px; }
svg.spark { width:80px; height:22px; display:block; }
svg.spark polyline { fill:none; stroke-width:1.5; stroke:currentColor; }
.muted { color:var(--muted); } .small { font-size:12px; margin-top:8px; }
.strip { display:flex; gap:8px; overflow-x:auto; scrollbar-width:none; padding:12px 0 4px; }
.strip::-webkit-scrollbar { display:none; }
.tile { flex:none; display:flex; flex-direction:column; min-width:86px; padding:8px 10px;
  background:var(--card); border-radius:10px; box-shadow:var(--shadow); font:13px system-ui, sans-serif; }
.tl { color:var(--muted); font-size:12px; } .tp { font-weight:700; font-size:15px; font-variant-numeric:tabular-nums; }
.tc { font-size:12.5px; font-weight:600; font-variant-numeric:tabular-nums; }
.more { flex:none; align-self:center; font:600 13px system-ui, sans-serif; color:var(--link); background:none;
  border:1px dashed var(--line); border-radius:10px; padding:16px 12px; cursor:pointer; }
@media (max-width:520px) { .wk { display:none; } col.c-px { width:60px; } col.c-ch { width:52px; }
  col.c-sp { width:46px; } svg.spark { width:44px !important; } td.sp { width:60px; } svg.spark { width:56px; }
  table.mk { font-size:13px; } table.mk td { padding:5px 3px; } }
"""

if __name__ == "__main__":
    print(board_html()[:2000])
