"""Market screener — Yahoo Finance predefined screeners, three buckets.

HIGH RISK / HIGH REWARD  — small/mid cap growth names with sustainable momentum
SAFE & SOLID             — large cap quality at reasonable valuation
DIP OPPORTUNITY          — quality stocks down today, trend intact — genuine buy-the-dip candidates

Scoring philosophy:
  - Bell-curve functions reward stocks in the OPTIMAL range; extremes score lower
  - A stock up 700% in a year has already played out — less upside, so lower score
  - Cyclical earnings spikes (e.g. semiconductor trough-to-peak) get dampened via sqrt
  - Day-change spikes (>12%) are excluded — one-time news events, not sustained signals

Yahoo Finance API field quirks:
  regularMarketChangePercent        → PERCENTAGE (14.9  = +14.9%)
  fiftyTwoWeekChangePercent         → PERCENTAGE (-48.5 = -48.5%)
  fiftyTwoWeekHighChangePercent     → FRACTION   (-0.63 = -63%)
  twoHundredDayAverageChangePercent → FRACTION   (-0.44 = -44%)
All stored as fractions internally (divide pct fields by 100).
"""
from __future__ import annotations

import concurrent.futures
import math
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
    category:     str               # "high_risk" | "safe" | "dip"
    market_cap:   Optional[float]   = None
    price:        Optional[float]   = None
    day_chg:      Optional[float]   = None   # fraction  (+0.05 = +5%)
    week52_chg:   Optional[float]   = None   # fraction  (+0.50 = +50%)
    vs_52w_high:  Optional[float]   = None   # fraction from 52w high (0 = AT high, -0.3 = 30% below)
    vs_ma200:     Optional[float]   = None   # fraction from 200d MA
    pe_forward:   Optional[float]   = None
    pe_trailing:  Optional[float]   = None
    eps_growth:   Optional[float]   = None   # implied: (fwd EPS – TTM EPS) / |TTM EPS|
    score:        float             = 0.0


# ── Fetch helpers ──────────────────────────────────────────────────────────────

def _get_predefined(scr_id: str, count: int = 100) -> list[dict]:
    url    = "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved"
    params = {"scrIds": scr_id, "start": 0, "count": count,
              "formatted": "false", "lang": "en-US", "region": "US"}
    try:
        r = requests.get(url, params=params,
                         headers={"User-Agent": _UA, "Accept": "application/json"},
                         timeout=_TIMEOUT)
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

    # PERCENTAGE fields → divide by 100
    w52_raw = q.get("fiftyTwoWeekChangePercent")
    day_raw = q.get("regularMarketChangePercent")
    week52  = w52_raw / 100.0 if w52_raw is not None else None
    day_chg = day_raw / 100.0 if day_raw is not None else None

    # FRACTION fields — already normalised
    vs_ma200    = q.get("twoHundredDayAverageChangePercent")
    vs_52w_high = q.get("fiftyTwoWeekHighChangePercent")   # 0 = at high, -0.3 = 30% below

    return QuoteRow(
        symbol      = q.get("symbol", ""),
        name        = (q.get("longName") or q.get("shortName") or q.get("symbol", ""))[:44],
        category    = category,
        market_cap  = q.get("marketCap"),
        price       = q.get("regularMarketPrice"),
        day_chg     = day_chg,
        week52_chg  = week52,
        vs_52w_high = vs_52w_high,
        vs_ma200    = vs_ma200,
        pe_forward  = q.get("forwardPE"),
        pe_trailing = q.get("trailingPE"),
        eps_growth  = eps_growth,
    )


# ── Scoring ────────────────────────────────────────────────────────────────────
# Bell-curve helper: peaks at 1.0 when val == optimal, falls symmetrically

def _bell(val: float, optimal: float, width: float) -> float:
    return math.exp(-((val - optimal) / width) ** 2)


def _score_hr(r: QuoteRow) -> float:
    """
    High Risk / High Reward scoring (0–100).

    Rewards:
      - Healthy EPS growth (dampened via sqrt to avoid cyclical spikes dominating)
      - 52w momentum in the SWEET SPOT (30–120%) — stocks already up 300%+ score lower
      - Mild positive day momentum (0.5–6%) — avoids one-day news spikes
      - Reasonable valuation even for growth names

    Penalises:
      - Stocks already extended far above 52w high (less upside remaining)
      - Day moves > 12% (likely a one-time catalyst, not sustained)
      - Deeply negative earnings growth
    """
    s = 0.0

    # ── EPS growth (0–40 pts): sqrt-damped to reduce cyclical spikes ──────────
    if r.eps_growth is not None:
        if r.eps_growth > 0:
            # sqrt dampens extremes: 25% → 12.5, 100% → 25, 400% → 50 → capped
            s += min(40.0, math.sqrt(r.eps_growth) * 25.0)
        elif r.eps_growth < -0.20:
            s -= 8.0   # declining earnings is a red flag

    # ── 52-week momentum (0–35 pts): bell curve, peak at ~70% gain ───────────
    if r.week52_chg is not None:
        w = r.week52_chg
        if w > -0.30:   # not a major downtrend
            # Peak at 70% annual gain; stocks up 300%+ score near 0
            pts = 35.0 * _bell(w, optimal=0.70, width=0.65)
            s += max(0.0, pts)

    # ── Valuation reasonableness (0–15 pts) ───────────────────────────────────
    if r.pe_forward is not None and r.pe_forward > 0:
        if r.pe_forward <= 20:
            s += 15.0    # cheap for a growth name
        elif r.pe_forward <= 35:
            s += 10.0    # fair
        elif r.pe_forward <= 55:
            s += 5.0     # stretched but acceptable
        # > 55x → 0

    # ── Day momentum (0–10 pts): gentle positive only ─────────────────────────
    if r.day_chg is not None:
        if 0.005 <= r.day_chg <= 0.06:
            s += 10.0   # healthy move, 0.5–6%
        elif 0.0 < r.day_chg <= 0.12:
            s += 5.0    # decent but larger
        # > 12% day → skip (one-time catalyst, not reliable signal)

    # ── Proximity to 52w high (0–10 pts bonus): near but not past ─────────────
    if r.vs_52w_high is not None:
        if -0.10 <= r.vs_52w_high <= 0.0:
            s += 10.0   # within 10% of 52w high — strong trend
        elif -0.25 <= r.vs_52w_high < -0.10:
            s += 5.0    # pulling back from high — potential re-entry

    return round(min(100.0, max(0.0, s)), 1)


def _score_safe(r: QuoteRow) -> float:
    """
    Safe & Solid scoring (0–100).

    Rewards:
      - Forward P/E in the attractive 10–25x range (not too cheap = value trap,
        not too dear = growth priced in)
      - Healthy distance above 200d MA (5–25% = trend confirmed, not overextended)
      - Moderate 52w gain (10–60%)
      - Positive EPS growth

    Penalises:
      - PE < 8 (often a value trap or cyclical trough)
      - > 40% above 200MA (overextended)
    """
    s = 0.0

    # ── Forward P/E (0–35 pts): sweet spot 12–25x ─────────────────────────────
    if r.pe_forward is not None and r.pe_forward > 0:
        if 10.0 <= r.pe_forward <= 25.0:
            s += 35.0                        # prime value range
        elif 25.0 < r.pe_forward <= 35.0:
            s += 22.0                        # fair for quality
        elif 8.0 <= r.pe_forward < 10.0:
            s += 18.0                        # cheap but might be a trap
        elif 35.0 < r.pe_forward <= 45.0:
            s += 12.0
        elif r.pe_forward < 8.0:
            s += 8.0                         # too cheap = warning sign

    # ── vs 200d MA (0–30 pts): healthy above, penalise extremes ─────────────
    if r.vs_ma200 is not None:
        if 0.05 <= r.vs_ma200 <= 0.25:
            s += 30.0   # healthy 5–25% above MA
        elif 0.0 < r.vs_ma200 < 0.05:
            s += 18.0   # barely above — trend fragile
        elif 0.25 < r.vs_ma200 <= 0.40:
            s += 18.0   # extended but still trending
        elif r.vs_ma200 > 0.40:
            s += 8.0    # very extended — pullback risk
        # Below MA → 0

    # ── 52w momentum (0–20 pts): moderate positive ───────────────────────────
    if r.week52_chg is not None and r.week52_chg > 0:
        pts = 20.0 * _bell(r.week52_chg, optimal=0.35, width=0.30)
        s += max(0.0, pts)

    # ── EPS growth (0–15 pts): quality check ─────────────────────────────────
    if r.eps_growth is not None and r.eps_growth > 0:
        s += min(15.0, math.sqrt(r.eps_growth) * 15.0)

    return round(min(100.0, max(0.0, s)), 1)


def _score_dip(r: QuoteRow) -> float:
    """
    Dip Opportunity scoring (0–100).

    Target: quality stocks having a bad day inside an otherwise healthy uptrend.
    The goal is to separate 'the market overreacted' from 'this thing is actually broken'.

    Rewards:
      - Clean pullback (−1% to −5%) — enough to be a real dip, not a crash
      - Stock still above 200d MA (uptrend intact; today is a re-entry)
      - Positive 52w return (this is a dip IN a bull run, not a continued decline)
      - Strong EPS growth — fundamentals support buying weakness

    Penalises:
      - Day drops > 12% (news-driven or real problem — not a dip, don't knife-catch)
      - Below 200MA (trend already broken)
      - Negative 52w return (this stock has been declining, not dipping)
      - Shrinking earnings
    """
    if r.day_chg is None or r.day_chg >= 0:
        return 0.0

    s = 0.0

    # ── Dip quality (0–25 pts): sweet spot −1.5% to −5% ─────────────────────
    dip = r.day_chg   # negative fraction, e.g. −0.025
    if -0.12 <= dip < -0.005:
        # Bell curve peaks at −2.5% drop; very shallow or crash-level drops score low
        pts = 25.0 * _bell(dip, optimal=-0.025, width=0.028)
        s += max(0.0, pts)

    # ── EPS growth (0–30 pts): fundamentals must justify buying the dip ──────
    if r.eps_growth is not None:
        if r.eps_growth > 0:
            s += min(30.0, math.sqrt(r.eps_growth) * 20.0)
        elif r.eps_growth < -0.20:
            s -= 10.0   # earnings declining = deterioration, not a dip

    # ── Trend health via 200MA (0–25 pts): above MA = dip in uptrend ─────────
    if r.vs_ma200 is not None:
        if 0.0 <= r.vs_ma200 <= 0.25:
            s += 25.0   # healthy 0–25% above: trend intact
        elif 0.25 < r.vs_ma200 <= 0.45:
            s += 18.0   # extended but still trending up
        elif -0.05 <= r.vs_ma200 < 0.0:
            s += 12.0   # just below MA — borderline
        elif -0.15 <= r.vs_ma200 < -0.05:
            s += 5.0    # weakening trend
        # < −15% below MA → 0 (broken trend, not a dip)

    # ── 52w return (0–20 pts): must be positive — dip IN a bull run ──────────
    if r.week52_chg is not None and r.week52_chg > 0:
        # Bell curve peak at +35% annual gain (healthy momentum, not exhausted)
        pts = 20.0 * _bell(r.week52_chg, optimal=0.35, width=0.45)
        s += max(0.0, pts)
    # Negative 52w → 0 bonus: declining stocks aren't dip opportunities

    return round(min(100.0, max(0.0, s)), 1)


# ── Main entry point ───────────────────────────────────────────────────────────

def run_screen(progress_cb=None) -> tuple[list[QuoteRow], list[QuoteRow], list[QuoteRow]]:
    """Fetch and return (high_risk_rows, safe_rows, dip_rows), sorted by score desc."""
    tasks = {
        "hr1": ("aggressive_small_caps",    100, "high_risk"),
        "hr2": ("growth_technology_stocks",  60, "high_risk"),
        "sf1": ("undervalued_large_caps",   100, "safe"),
        "sf2": ("undervalued_growth_stocks", 60, "safe"),
        "dp1": ("day_losers",               100, "dip"),
    }
    raw: dict[str, list[dict]] = {}
    done = 0

    def _fetch(key, scr_id, count, _cat):
        return key, _get_predefined(scr_id, count)

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(_fetch, k, sid, cnt, cat): k
                   for k, (sid, cnt, cat) in tasks.items()}
        for fut in concurrent.futures.as_completed(futures):
            key, quotes = fut.result()
            raw[key] = quotes
            done += 1
            if progress_cb:
                progress_cb(done / len(tasks))

    def _merge(keys, category):
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
    dip_rows  = _merge(["dp1"],        "dip")

    # Filter dip: must be down at least 0.5% today, and not a full crash (>12%)
    dip_rows = [r for r in dip_rows
                if r.day_chg is not None and -0.12 <= r.day_chg < -0.005]

    for r in hr_rows:   r.score = _score_hr(r)
    for r in safe_rows: r.score = _score_safe(r)
    for r in dip_rows:  r.score = _score_dip(r)

    hr_rows.sort(  key=lambda x: x.score, reverse=True)
    safe_rows.sort(key=lambda x: x.score, reverse=True)
    dip_rows.sort( key=lambda x: x.score, reverse=True)

    return hr_rows, safe_rows, dip_rows


# ── Formatting helpers ─────────────────────────────────────────────────────────

def _mc(v):
    if v is None: return "—"
    if v >= 1e12: return f"${v/1e12:.1f}T"
    if v >= 1e9:  return f"${v/1e9:.1f}B"
    if v >= 1e6:  return f"${v/1e6:.0f}M"
    return f"${v:,.0f}"

def _pct(v):
    if v is None: return "—"
    return f"{'+'if v >= 0 else ''}{v*100:.1f}%"

def _pe(v):
    return "—" if (v is None or v <= 0) else f"{v:.1f}×"

def _score_bar(score, accent):
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

def _cls(val, lo, hi, invert=False):
    if val is None: return "cell-dim"
    norm = (val - lo) / max(hi - lo, 1e-9)
    norm = max(0.0, min(1.0, norm))
    if invert: norm = 1.0 - norm
    if norm >= 0.62: return "cell-green"
    if norm >= 0.35: return "cell-amber"
    return "cell-red"


# ── HTML table ─────────────────────────────────────────────────────────────────

def render_table(rows: list[QuoteRow], accent: str, limit: int = 50) -> str:
    is_hr = rows and rows[0].category == "high_risk"
    html_rows = []
    for rank, r in enumerate(rows[:limit], 1):
        day_cls = _cls(r.day_chg,    lo=-0.03, hi=0.08)
        w52_cls = _cls(r.week52_chg, lo=-0.20, hi=1.20)
        eps_cls = _cls(r.eps_growth, lo=-0.10, hi=0.80)
        pe_cls  = _cls(r.pe_forward, lo=5,     hi=50, invert=True)
        ma_cls  = _cls(r.vs_ma200,   lo=-0.15, hi=0.35)

        price_s = f"${r.price:,.2f}" if r.price else "—"
        sc_bar  = _score_bar(r.score, accent)
        name_s  = r.name[:34] + "…" if len(r.name) > 34 else r.name

        pe_cell = ("" if is_hr else
                   f'<td class="{pe_cls}" style="text-align:right;font-family:\'JetBrains Mono\',monospace;white-space:nowrap">{_pe(r.pe_forward)}</td>')
        ma_cell = ("" if is_hr else
                   f'<td class="{ma_cls}" style="text-align:right;font-family:\'JetBrains Mono\',monospace;white-space:nowrap">{_pct(r.vs_ma200)}</td>')

        html_rows.append(f"""
<tr>
  <td style="color:#374151;text-align:center;width:28px;font-size:0.78rem">{rank}</td>
  <td style="min-width:120px">
    <div style="font-family:'JetBrains Mono',monospace;font-weight:700;color:#f4f5f7;font-size:0.9rem">{r.symbol}</div>
    <div style="color:#4b5563;font-size:0.73rem;margin-top:1px">{name_s}</div>
  </td>
  <td style="color:#6b7280;font-size:0.82rem;white-space:nowrap">{_mc(r.market_cap)}</td>
  <td style="white-space:nowrap">
    <div style="font-family:'JetBrains Mono',monospace;font-size:0.86rem;color:#d1d5db">{price_s}</div>
    <div class="{day_cls}" style="font-size:0.73rem">{_pct(r.day_chg)}</div>
  </td>
  <td class="{eps_cls}" style="text-align:right;font-family:'JetBrains Mono',monospace;font-size:0.86rem;white-space:nowrap">{_pct(r.eps_growth)}</td>
  {pe_cell}
  <td class="{w52_cls}" style="text-align:right;font-family:'JetBrains Mono',monospace;font-size:0.86rem;white-space:nowrap">{_pct(r.week52_chg)}</td>
  {ma_cell}
  <td style="padding-right:18px">{sc_bar}</td>
</tr>""")

    pe_hdr = "" if is_hr else '<th style="text-align:right">Fwd P/E</th>'
    ma_hdr = "" if is_hr else '<th style="text-align:right">vs 200MA</th>'

    return f"""
<table class="screener-table">
<thead>
<tr>
  <th style="width:28px">#</th><th>Stock</th><th>Mkt Cap</th><th>Price</th>
  <th style="text-align:right">EPS Grw</th>
  {pe_hdr}
  <th style="text-align:right">52-week</th>
  {ma_hdr}
  <th>Score</th>
</tr>
</thead>
<tbody>{"".join(html_rows)}</tbody>
</table>"""
