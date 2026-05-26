"""Market screener — Yahoo Finance predefined screeners, two buckets.

HIGH RISK / HIGH REWARD  — aggressive small/mid cap growth names
SAFE & SOLID             — large cap quality at reasonable valuation

Field quirks from Yahoo Finance API (discovered empirically):
  regularMarketChangePercent   → PERCENTAGE  (14.9  = +14.9%)
  fiftyTwoWeekChangePercent    → PERCENTAGE  (-48.5 = -48.5%)
  fiftyTwoWeekHighChangePercent   → FRACTION  (-0.63 = -63%)
  twoHundredDayAverageChangePercent → FRACTION (-0.44 = -44%)
We normalise everything to fractions internally.
"""
from __future__ import annotations

import concurrent.futures
from dataclasses import dataclass
from typing import Optional

import requests

_UA      = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
_TIMEOUT = 18


# ── Data model ─────────────────────────────────────────────────────────────────

@dataclass
class QuoteRow:
    symbol:       str
    name:         str
    category:     str               # "high_risk" | "safe"
    market_cap:   Optional[float]   = None
    price:        Optional[float]   = None
    day_chg:      Optional[float]   = None   # fraction  (+0.05 = +5%)
    week52_chg:   Optional[float]   = None   # fraction  (+0.50 = +50%)
    vs_ma200:     Optional[float]   = None   # fraction  (+0.10 = 10% above 200d MA)
    pe_forward:   Optional[float]   = None
    pe_trailing:  Optional[float]   = None
    eps_growth:   Optional[float]   = None   # implied (fwd EPS - TTM EPS) / |TTM EPS|
    score:        float             = 0.0


# ── Fetch helpers ──────────────────────────────────────────────────────────────

def _get_predefined(scr_id: str, count: int = 100) -> list[dict]:
    url    = "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved"
    params = {
        "scrIds":    scr_id,
        "start":     0,
        "count":     count,
        "formatted": "false",
        "lang":      "en-US",
        "region":    "US",
    }
    try:
        r = requests.get(
            url, params=params,
            headers={"User-Agent": _UA, "Accept": "application/json"},
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        result = r.json().get("finance", {}).get("result") or []
        return result[0].get("quotes", []) if result else []
    except Exception:
        return []


def _parse(q: dict, category: str) -> QuoteRow:
    # Implied forward EPS growth
    eps_fwd = q.get("epsForward")
    eps_ttm = q.get("epsTrailingTwelveMonths")
    eps_growth: Optional[float] = None
    if eps_fwd is not None and eps_ttm is not None and eps_ttm > 0:
        eps_growth = (eps_fwd - eps_ttm) / eps_ttm

    # 52w change is stored as PERCENTAGE → convert to fraction
    w52_pct = q.get("fiftyTwoWeekChangePercent")
    week52  = w52_pct / 100.0 if w52_pct is not None else None

    # Day change is PERCENTAGE → fraction
    day_pct = q.get("regularMarketChangePercent")
    day_chg = day_pct / 100.0 if day_pct is not None else None

    # vs 200d MA is already a FRACTION
    vs_ma200 = q.get("twoHundredDayAverageChangePercent")

    return QuoteRow(
        symbol      = q.get("symbol", ""),
        name        = (q.get("longName") or q.get("shortName") or q.get("symbol", ""))[:44],
        category    = category,
        market_cap  = q.get("marketCap"),
        price       = q.get("regularMarketPrice"),
        day_chg     = day_chg,
        week52_chg  = week52,
        vs_ma200    = vs_ma200,
        pe_forward  = q.get("forwardPE"),
        pe_trailing = q.get("trailingPE"),
        eps_growth  = eps_growth,
    )


# ── Scoring ────────────────────────────────────────────────────────────────────

def _score_hr(r: QuoteRow) -> float:
    """High Risk: 52w momentum + implied EPS growth + day momentum."""
    s = 0.0
    # 52-week price momentum (0–50 pts) — rewarded above 0
    if r.week52_chg is not None and r.week52_chg > 0:
        s += min(50.0, r.week52_chg * 100)          # +50% 52w → 50 pts
    # Implied EPS growth (0–35 pts)
    if r.eps_growth is not None and r.eps_growth > 0:
        s += min(35.0, r.eps_growth * 70)            # +50% EPS grw → 35 pts
    # Today's momentum (0–15 pts) — volatile movers score higher
    if r.day_chg is not None and r.day_chg > 0:
        s += min(15.0, r.day_chg * 150)              # +10% day → 15 pts
    return round(s, 1)


def _score_safe(r: QuoteRow) -> float:
    """Safe: forward value + MA trend + 52w momentum."""
    s = 0.0
    # Forward P/E value (0–40 pts) — lower is better
    if r.pe_forward is not None and 0 < r.pe_forward < 100:
        s += max(0.0, min(40.0, 800.0 / r.pe_forward))   # PE 20 → 40 pts
    # Above 200d MA (0–30 pts)
    if r.vs_ma200 is not None and r.vs_ma200 > 0:
        s += min(30.0, r.vs_ma200 * 150)                  # +20% above → 30 pts
    # 52-week positive momentum (0–30 pts)
    if r.week52_chg is not None and r.week52_chg > 0:
        s += min(30.0, r.week52_chg * 60)                 # +50% 52w → 30 pts
    return round(s, 1)


# ── Main entry point ───────────────────────────────────────────────────────────

def run_screen(
    progress_cb=None,
) -> tuple[list[QuoteRow], list[QuoteRow]]:
    """Fetch and return (high_risk_rows, safe_rows), both sorted by score desc."""
    tasks = {
        "hr1": ("aggressive_small_caps",   100, "high_risk"),
        "hr2": ("growth_technology_stocks", 60, "high_risk"),
        "sf1": ("undervalued_large_caps",  100, "safe"),
        "sf2": ("undervalued_growth_stocks", 60, "safe"),
    }
    raw: dict[str, list[dict]] = {}
    done = 0

    def _fetch(key: str, scr_id: str, count: int, _cat: str):
        return key, _get_predefined(scr_id, count)

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures = {
            pool.submit(_fetch, k, sid, cnt, cat): k
            for k, (sid, cnt, cat) in tasks.items()
        }
        for fut in concurrent.futures.as_completed(futures):
            key, quotes = fut.result()
            raw[key] = quotes
            done += 1
            if progress_cb:
                progress_cb(done / len(tasks))

    def _merge(keys: list[str], category: str) -> list[QuoteRow]:
        seen: set[str] = set()
        rows: list[QuoteRow] = []
        for k in keys:
            for q in raw.get(k, []):
                sym = q.get("symbol", "")
                if sym and sym not in seen:
                    seen.add(sym)
                    rows.append(_parse(q, category))
        return rows

    hr_rows   = _merge(["hr1", "hr2"], "high_risk")
    safe_rows = _merge(["sf1", "sf2"], "safe")

    for r in hr_rows:
        r.score = _score_hr(r)
    for r in safe_rows:
        r.score = _score_safe(r)

    hr_rows.sort(  key=lambda x: x.score, reverse=True)
    safe_rows.sort(key=lambda x: x.score, reverse=True)

    return hr_rows, safe_rows


# ── Formatting helpers ─────────────────────────────────────────────────────────

def _mc(v: Optional[float]) -> str:
    if v is None:
        return "—"
    if v >= 1e12:
        return f"${v/1e12:.1f}T"
    if v >= 1e9:
        return f"${v/1e9:.1f}B"
    if v >= 1e6:
        return f"${v/1e6:.0f}M"
    return f"${v:,.0f}"


def _pct(v: Optional[float]) -> str:
    """Render a fraction as a coloured percentage string."""
    if v is None:
        return "—"
    return f"{'+'if v >= 0 else ''}{v*100:.1f}%"


def _pe(v: Optional[float]) -> str:
    return "—" if (v is None or v <= 0) else f"{v:.1f}×"


def _score_bar(score: float, accent: str) -> str:
    pct = min(100, max(0, score))
    return (
        f'<div style="display:flex;align-items:center;gap:7px">'
        f'<div style="width:48px;height:4px;background:#1e2330;border-radius:3px;flex-shrink:0">'
        f'<div style="width:{pct:.0f}%;height:4px;background:{accent};border-radius:3px"></div>'
        f'</div>'
        f'<span style="font-family:\'JetBrains Mono\',monospace;font-size:0.82rem;'
        f'color:{accent};font-weight:700">{score:.0f}</span>'
        f'</div>'
    )


def _cls(val, lo: float, hi: float, invert: bool = False) -> str:
    if val is None:
        return "cell-dim"
    norm = (val - lo) / max(hi - lo, 1e-9)
    norm = max(0.0, min(1.0, norm))
    if invert:
        norm = 1.0 - norm
    if norm >= 0.62:
        return "cell-green"
    if norm >= 0.35:
        return "cell-amber"
    return "cell-red"


# ── HTML table ─────────────────────────────────────────────────────────────────

def render_table(rows: list[QuoteRow], accent: str, limit: int = 50) -> str:
    is_hr = rows and rows[0].category == "high_risk"
    html_rows = []
    for rank, r in enumerate(rows[:limit], 1):
        day_cls  = _cls(r.day_chg,   lo=-0.03, hi=0.08)
        w52_cls  = _cls(r.week52_chg, lo=-0.20, hi=0.80)
        eps_cls  = _cls(r.eps_growth, lo=-0.10, hi=0.50)
        pe_cls   = _cls(r.pe_forward, lo=5, hi=50, invert=True)
        ma_cls   = _cls(r.vs_ma200,  lo=-0.15, hi=0.30)

        price_s  = f"${r.price:,.2f}" if r.price else "—"
        day_s    = _pct(r.day_chg)
        w52_s    = _pct(r.week52_chg)
        eps_s    = _pct(r.eps_growth)
        pe_s     = _pe(r.pe_forward)
        ma_s     = _pct(r.vs_ma200)
        mc_s     = _mc(r.market_cap)
        sc_bar   = _score_bar(r.score, accent)
        name_s   = r.name[:34] + "…" if len(r.name) > 34 else r.name

        pe_cell  = "" if is_hr else f'<td class="{pe_cls}" style="text-align:right;font-family:\'JetBrains Mono\',monospace;white-space:nowrap">{pe_s}</td>'
        ma_cell  = "" if is_hr else f'<td class="{ma_cls}" style="text-align:right;font-family:\'JetBrains Mono\',monospace;white-space:nowrap">{ma_s}</td>'

        html_rows.append(f"""
<tr>
  <td style="color:#374151;text-align:center;width:28px;font-size:0.78rem">{rank}</td>
  <td style="min-width:120px">
    <div style="font-family:'JetBrains Mono',monospace;font-weight:700;color:#f4f5f7;font-size:0.9rem;letter-spacing:-0.01em">{r.symbol}</div>
    <div style="color:#4b5563;font-size:0.73rem;margin-top:1px">{name_s}</div>
  </td>
  <td style="color:#6b7280;font-size:0.82rem;white-space:nowrap">{mc_s}</td>
  <td style="white-space:nowrap">
    <div style="font-family:'JetBrains Mono',monospace;font-size:0.86rem;color:#d1d5db">{price_s}</div>
    <div class="{day_cls}" style="font-size:0.73rem">{day_s}</div>
  </td>
  <td class="{eps_cls}" style="text-align:right;font-family:'JetBrains Mono',monospace;font-size:0.86rem;white-space:nowrap">{eps_s}</td>
  {pe_cell}
  <td class="{w52_cls}" style="text-align:right;font-family:'JetBrains Mono',monospace;font-size:0.86rem;white-space:nowrap">{w52_s}</td>
  {ma_cell}
  <td style="padding-right:18px">{sc_bar}</td>
</tr>""")

    # Build header
    pe_hdr = "" if is_hr else '<th style="text-align:right">Fwd P/E</th>'
    ma_hdr = "" if is_hr else '<th style="text-align:right">vs 200MA</th>'

    return f"""
<table class="screener-table">
<thead>
<tr>
  <th style="width:28px">#</th>
  <th>Stock</th>
  <th>Mkt Cap</th>
  <th>Price</th>
  <th style="text-align:right">EPS Grw</th>
  {pe_hdr}
  <th style="text-align:right">52-week</th>
  {ma_hdr}
  <th>Score</th>
</tr>
</thead>
<tbody>{"".join(html_rows)}</tbody>
</table>"""
