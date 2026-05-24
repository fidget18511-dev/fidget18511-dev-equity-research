"""Fetch fundamentals + OHLCV using direct Yahoo Finance HTTP (no auth required).

The fc.yahoo.com cookie endpoint that yfinance depends on is unreachable on some
networks. We use only the chart endpoint (open, no auth) plus a regex scrape of
the public quote page, which embeds fundamentals as JSON in the HTML.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import pandas as pd
import requests

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
_TIMEOUT = 15


@dataclass
class Snapshot:
    ticker: str
    name: str | None
    sector: str | None
    industry: str | None
    price: float | None
    market_cap: float | None
    pe_ttm: float | None
    pe_forward: float | None
    ev_ebitda: float | None
    p_fcf: float | None
    revenue_growth_yoy: float | None
    ebitda_margin: float | None
    net_debt_to_ebitda: float | None
    short_pct_float: float | None
    rsi_14: float | None
    ma_50: float | None
    ma_200: float | None
    vs_ma_200_pct: float | None
    above_ma_50: bool | None
    above_ma_200: bool | None
    week52_high: float | None
    week52_low: float | None


def _http_get(url: str) -> requests.Response:
    return requests.get(url, headers={"User-Agent": _UA, "Accept": "*/*"}, timeout=_TIMEOUT)


def _fetch_chart(ticker: str) -> tuple[pd.DataFrame, dict]:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=2y"
    r = _http_get(url)
    r.raise_for_status()
    data = r.json()
    result_list = data.get("chart", {}).get("result")
    if not result_list:
        err = data.get("chart", {}).get("error", {}).get("description", "unknown error")
        raise ValueError(f"Yahoo chart error for {ticker}: {err}")

    result = result_list[0]
    meta = result.get("meta") or {}
    ts = result.get("timestamp") or []
    quote = (result.get("indicators", {}).get("quote") or [{}])[0]

    df = pd.DataFrame(
        {
            "Open": quote.get("open"),
            "High": quote.get("high"),
            "Low": quote.get("low"),
            "Close": quote.get("close"),
            "Volume": quote.get("volume"),
        },
        index=pd.to_datetime(ts, unit="s", utc=True),
    ).dropna(subset=["Close"])
    return df, meta


_NUM = r"(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)"


def _extract_raw(html: str, key: str) -> float | None:
    m = re.search(rf'\\?"{re.escape(key)}\\?":\s*\{{\\?"raw\\?":\s*{_NUM}', html)
    if m:
        return float(m.group(1))
    m = re.search(rf'\\?"{re.escape(key)}\\?":\s*{_NUM}(?=[,}}\]])', html)
    return float(m.group(1)) if m else None


def _extract_str(html: str, key: str) -> str | None:
    m = re.search(rf'\\?"{re.escape(key)}\\?":\s*\\?"([^"\\]+)\\?"', html)
    return m.group(1) if m else None


def _ticker_window(html: str, ticker: str) -> str:
    """Slice the HTML to the AAPL-specific store block so we don't pick up
    longName / sector from 'people also watch' widgets earlier on the page."""
    anchor = re.search(rf'\\?"symbol\\?":\s*\\?"{re.escape(ticker)}\\?"', html)
    if not anchor:
        return html
    return html[anchor.start(): anchor.start() + 20000]


def _fetch_fundamentals(ticker: str) -> dict:
    try:
        r = _http_get(f"https://finance.yahoo.com/quote/{ticker}/")
        r.raise_for_status()
        h = r.text
    except Exception:
        return {}

    win = _ticker_window(h, ticker)
    return {
        "name": _extract_str(win, "longName") or _extract_str(win, "shortName"),
        "sector": _extract_str(win, "sector") or _extract_str(h, "sector"),
        "industry": _extract_str(win, "industry") or _extract_str(h, "industry"),
        "trailingPE": _extract_raw(h, "trailingPE"),
        "forwardPE": _extract_raw(h, "forwardPE"),
        "marketCap": _extract_raw(h, "marketCap"),
        "enterpriseToEbitda": _extract_raw(h, "enterpriseToEbitda"),
        "ebitdaMargins": _extract_raw(h, "ebitdaMargins"),
        "revenueGrowth": _extract_raw(h, "revenueGrowth"),
        "totalDebt": _extract_raw(h, "totalDebt"),
        "totalCash": _extract_raw(h, "totalCash"),
        "ebitda": _extract_raw(h, "ebitda"),
        "freeCashflow": _extract_raw(h, "freeCashflow"),
        "shortPercentOfFloat": _extract_raw(h, "shortPercentOfFloat"),
    }


def _rsi(close: pd.Series, period: int = 14) -> float | None:
    if len(close) < period + 1:
        return None
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, pd.NA)
    rsi = 100 - 100 / (1 + rs)
    val = rsi.iloc[-1]
    return float(val) if pd.notna(val) else None


def fetch_snapshot(ticker: str) -> tuple[Snapshot, pd.DataFrame]:
    ticker = ticker.upper().strip()
    hist, meta = _fetch_chart(ticker)
    if hist.empty:
        raise ValueError(f"No price history available for '{ticker}'.")

    close = hist["Close"]
    price = float(close.iloc[-1])
    ma_50 = float(close.tail(50).mean()) if len(close) >= 50 else None
    ma_200 = float(close.tail(200).mean()) if len(close) >= 200 else None

    f = _fetch_fundamentals(ticker)
    market_cap = f.get("marketCap")
    fcf = f.get("freeCashflow")
    p_fcf = (market_cap / fcf) if (market_cap and fcf and fcf > 0) else None

    total_debt = f.get("totalDebt")
    cash = f.get("totalCash")
    ebitda = f.get("ebitda")
    net_debt_to_ebitda = None
    if total_debt is not None and ebitda and ebitda > 0:
        net_debt_to_ebitda = (total_debt - (cash or 0)) / ebitda

    return Snapshot(
        ticker=ticker,
        name=f.get("name"),
        sector=f.get("sector"),
        industry=f.get("industry"),
        price=price,
        market_cap=market_cap,
        pe_ttm=f.get("trailingPE"),
        pe_forward=f.get("forwardPE"),
        ev_ebitda=f.get("enterpriseToEbitda"),
        p_fcf=p_fcf,
        revenue_growth_yoy=f.get("revenueGrowth"),
        ebitda_margin=f.get("ebitdaMargins"),
        net_debt_to_ebitda=net_debt_to_ebitda,
        short_pct_float=f.get("shortPercentOfFloat"),
        rsi_14=_rsi(close),
        ma_50=ma_50,
        ma_200=ma_200,
        vs_ma_200_pct=((price / ma_200 - 1) * 100) if ma_200 else None,
        above_ma_50=(price > ma_50) if ma_50 else None,
        above_ma_200=(price > ma_200) if ma_200 else None,
        week52_high=meta.get("fiftyTwoWeekHigh"),
        week52_low=meta.get("fiftyTwoWeekLow"),
    ), hist


def _fmt(v, kind: str = "num") -> str:
    if v is None:
        return "n/a"
    if kind == "pct_frac":
        return f"{v * 100:.1f}%"
    if kind == "pct":
        return f"{v:.1f}%"
    if kind == "mc":
        if v >= 1e12:
            return f"${v / 1e12:.2f}T"
        if v >= 1e9:
            return f"${v / 1e9:.2f}B"
        if v >= 1e6:
            return f"${v / 1e6:.2f}M"
        return f"${v:,.0f}"
    if kind == "price":
        return f"${v:,.2f}"
    return f"{v:.2f}"


def snapshot_to_markdown(s: Snapshot) -> str:
    rows = [
        ("Ticker", f"{s.ticker} — {s.name or '—'}"),
        ("Sector / Industry", f"{s.sector or '—'} / {s.industry or '—'}"),
        ("Price", _fmt(s.price, "price")),
        ("Market cap", _fmt(s.market_cap, "mc")),
        ("P/E (TTM)", _fmt(s.pe_ttm)),
        ("P/E (Forward)", _fmt(s.pe_forward)),
        ("EV/EBITDA", _fmt(s.ev_ebitda)),
        ("P/FCF", _fmt(s.p_fcf)),
        ("Revenue growth YoY", _fmt(s.revenue_growth_yoy, "pct_frac")),
        ("EBITDA margin", _fmt(s.ebitda_margin, "pct_frac")),
        ("Net debt / EBITDA", _fmt(s.net_debt_to_ebitda)),
        ("Short interest (% float)", _fmt(s.short_pct_float, "pct_frac")),
        ("RSI(14)", _fmt(s.rsi_14)),
        ("50-day MA", _fmt(s.ma_50, "price")),
        ("200-day MA", _fmt(s.ma_200, "price")),
        ("Price vs 200d MA", _fmt(s.vs_ma_200_pct, "pct")),
        ("52-week high", _fmt(s.week52_high, "price")),
        ("52-week low", _fmt(s.week52_low, "price")),
    ]
    body = "\n".join(f"| {k} | {v} |" for k, v in rows)
    return f"| Metric | Value |\n|---|---|\n{body}"
