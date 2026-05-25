"""Stock screener — parallel-fetch a curated universe and rank by composite score."""
from __future__ import annotations

import concurrent.futures
from dataclasses import dataclass
from typing import Callable

from data import Snapshot, fetch_snapshot

# ── Universe ──────────────────────────────────────────────────────────────────
UNIVERSE: list[tuple[str, str]] = [
    # AI / Cloud
    ("NVDA", "AI Chips"),
    ("MSFT", "Cloud / AI"),
    ("GOOGL", "Search / Cloud"),
    ("META", "Social / AI"),
    ("AMZN", "Cloud / E-comm"),
    # Consumer Tech
    ("AAPL", "Consumer Tech"),
    # Cybersecurity / Data
    ("CRWD", "Cybersecurity"),
    ("PLTR", "Data / AI"),
    ("AXON", "Public Safety"),
    # Semiconductors
    ("AVGO", "Semiconductors"),
    ("TSM", "Chip Mfg"),
    # Payments / Financials
    ("V", "Payments"),
    ("MA", "Payments"),
    ("JPM", "Banking"),
    # Healthcare / Pharma
    ("LLY", "GLP-1 Pharma"),
    ("NVO", "GLP-1 Pharma"),
    ("UNH", "Managed Care"),
    # Consumer / Other
    ("COST", "Warehouse Retail"),
    ("SPGI", "Financial Data"),
]


@dataclass
class ScreenResult:
    ticker: str
    label: str
    snap: Snapshot
    score: float
    quality: float      # 0–40
    momentum: float     # 0–35
    value_score: float  # 0–25
    error: str | None = None


def _score(snap: Snapshot) -> tuple[float, float, float, float]:
    """Returns (total, quality, momentum, value_score)."""
    # ── Quality (0–40): profitable growth ──────────────────────────────────
    q = 0.0
    if snap.revenue_growth_yoy is not None:
        # 20 %+ growth → full 20 pts
        q += min(20.0, max(0.0, snap.revenue_growth_yoy * 100))
    if snap.ebitda_margin is not None:
        # 25 %+ margin → full 20 pts
        q += min(20.0, max(0.0, snap.ebitda_margin * 80))

    # ── Momentum / Technical (0–35) ────────────────────────────────────────
    t = 0.0
    rsi = snap.rsi_14
    if rsi is not None:
        if 50 <= rsi <= 65:
            t += 20.0   # sweet spot: trending but not extended
        elif 40 <= rsi < 50:
            t += 14.0
        elif 65 < rsi <= 72:
            t += 12.0
        elif 30 <= rsi < 40:
            t += 6.0
        # RSI < 30 or > 72 → 0 pts
    if snap.above_ma_200:
        t += 10.0
    if snap.above_ma_50:
        t += 5.0

    # ── Value (0–25): inverse forward P/E ──────────────────────────────────
    v = 0.0
    if snap.pe_forward is not None and 0 < snap.pe_forward < 300:
        v = max(0.0, min(25.0, 500.0 / snap.pe_forward))   # 20× PE → 25 pts

    total = round(q + t + v, 1)
    return total, round(q, 1), round(t, 1), round(v, 1)


def _dummy_snap(ticker: str) -> Snapshot:
    return Snapshot(
        ticker=ticker, name=None, sector=None, industry=None,
        price=None, market_cap=None, pe_ttm=None, pe_forward=None,
        ev_ebitda=None, p_fcf=None, revenue_growth_yoy=None,
        ebitda_margin=None, net_debt_to_ebitda=None, short_pct_float=None,
        rsi_14=None, ma_50=None, ma_200=None, vs_ma_200_pct=None,
        above_ma_50=None, above_ma_200=None, week52_high=None, week52_low=None,
    )


def screen_universe(
    progress_cb: Callable[[float], None] | None = None,
) -> list[ScreenResult]:
    """Fetch all tickers concurrently, score, return sorted descending by score."""
    results: list[ScreenResult] = []

    def _fetch_one(item: tuple[str, str]) -> ScreenResult:
        ticker, label = item
        try:
            snap, _ = fetch_snapshot(ticker)
            total, q, t, v = _score(snap)
            return ScreenResult(
                ticker=ticker, label=label, snap=snap,
                score=total, quality=q, momentum=t, value_score=v,
            )
        except Exception as exc:
            return ScreenResult(
                ticker=ticker, label=label, snap=_dummy_snap(ticker),
                score=0.0, quality=0.0, momentum=0.0, value_score=0.0,
                error=str(exc),
            )

    done = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(_fetch_one, item): item for item in UNIVERSE}
        for fut in concurrent.futures.as_completed(futures):
            results.append(fut.result())
            done += 1
            if progress_cb:
                progress_cb(done / len(UNIVERSE))

    return sorted(results, key=lambda r: r.score, reverse=True)


# ── Table HTML renderer ────────────────────────────────────────────────────────

def _cls(val, lo: float, hi: float, invert: bool = False) -> str:
    """Map a value onto cell-green / cell-amber / cell-red."""
    if val is None:
        return "cell-dim"
    norm = (val - lo) / max(hi - lo, 1e-9)
    norm = max(0.0, min(1.0, norm))
    if invert:
        norm = 1.0 - norm
    if norm >= 0.65:
        return "cell-green"
    if norm >= 0.35:
        return "cell-amber"
    return "cell-red"


def _rsi_cls(rsi) -> str:
    if rsi is None:
        return "cell-dim"
    if 48 <= rsi <= 68:
        return "cell-green"
    if 38 <= rsi <= 78:
        return "cell-amber"
    return "cell-red"


def render_table(results: list[ScreenResult]) -> str:
    """Return a styled HTML table for use in st.markdown(unsafe_allow_html=True)."""
    rows = []
    rank = 0
    for r in results:
        if r.error:
            continue
        rank += 1
        s = r.snap

        def _p(v, mult=100, plus=True, suffix="%"):
            if v is None:
                return "—"
            return f"{'+' if plus and v > 0 else ''}{v * mult:.1f}{suffix}"

        def _f(v, fmt=".1f", suffix=""):
            return "—" if v is None else f"{v:{fmt}}{suffix}"

        pe_str   = f"{s.pe_forward:.1f}×" if s.pe_forward else "—"
        rg_str   = _p(s.revenue_growth_yoy)
        em_str   = _p(s.ebitda_margin, plus=False)
        rsi_str  = _f(s.rsi_14)
        ma_str   = f"{s.vs_ma_200_pct:+.1f}%" if s.vs_ma_200_pct is not None else "—"

        sc_cls  = _cls(r.score,                  lo=30, hi=80)
        pe_cls  = _cls(s.pe_forward,              lo=10, hi=60, invert=True)
        rg_cls  = _cls(s.revenue_growth_yoy,      lo=-0.05, hi=0.30)
        em_cls  = _cls(s.ebitda_margin,            lo=0.0,  hi=0.30)
        rs_cls  = _rsi_cls(s.rsi_14)
        ma_cls  = _cls(s.vs_ma_200_pct,           lo=-15,  hi=30)

        rows.append(f"""
<tr>
  <td style="color:#4b5563;text-align:center;width:36px">{rank}</td>
  <td style="font-family:'JetBrains Mono',monospace;font-weight:700;color:#f4f5f7;white-space:nowrap">{r.ticker}</td>
  <td style="color:#9ca3af;font-size:0.82rem;white-space:nowrap">{r.label}</td>
  <td class="{sc_cls}" style="text-align:center;font-weight:700;font-family:'JetBrains Mono',monospace">{r.score:.0f}</td>
  <td class="{pe_cls}" style="text-align:right;font-family:'JetBrains Mono',monospace">{pe_str}</td>
  <td class="{rg_cls}" style="text-align:right;font-family:'JetBrains Mono',monospace">{rg_str}</td>
  <td class="{em_cls}" style="text-align:right;font-family:'JetBrains Mono',monospace">{em_str}</td>
  <td class="{rs_cls}" style="text-align:right;font-family:'JetBrains Mono',monospace">{rsi_str}</td>
  <td class="{ma_cls}" style="text-align:right;font-family:'JetBrains Mono',monospace">{ma_str}</td>
</tr>""")

    return f"""
<table class="screener-table">
<thead>
<tr>
  <th style="width:36px">#</th>
  <th>Ticker</th>
  <th>Theme</th>
  <th style="text-align:center">Score</th>
  <th style="text-align:right">Fwd P/E</th>
  <th style="text-align:right">Rev Growth</th>
  <th style="text-align:right">EBITDA Mgn</th>
  <th style="text-align:right">RSI</th>
  <th style="text-align:right">vs 200MA</th>
</tr>
</thead>
<tbody>{"".join(rows)}</tbody>
</table>"""
