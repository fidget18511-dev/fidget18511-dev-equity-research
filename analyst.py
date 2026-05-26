"""Claude analyst — streams a structured equity report from a Snapshot."""
from __future__ import annotations

import os
from typing import Iterator

from anthropic import Anthropic
from dotenv import load_dotenv

from data import Snapshot, snapshot_to_markdown

load_dotenv(override=True)


def _api_key() -> str:
    """Resolve ANTHROPIC_API_KEY from env, then Streamlit secrets (for cloud)."""
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if key:
        return key
    try:
        import streamlit as st  # noqa: WPS433
        return st.secrets.get("ANTHROPIC_API_KEY", "")
    except Exception:
        return ""

MODEL = "claude-sonnet-4-6"

SYSTEM_PROMPT = """You are a rigorous investment research analyst. Your job is to produce clear, data-driven analysis that a professional investor can act on.

CORE BEHAVIOUR
- Be direct. Give a clear view. Don't hedge into meaninglessness.
- Use the figures in the snapshot the user provides. Do not invent numbers.
- If a metric is marked n/a, say so explicitly — do not fabricate.
- No boilerplate disclaimers.

OUTPUT FORMAT — produce exactly these sections in markdown:

## 1. Read of the snapshot
2-3 sentences interpreting what jumps out from the provided table.

## 2. Bull Case
3-5 numbered, concrete reasons to be long. Reference actual figures from the snapshot. Include catalysts, moats, valuation support.

## 3. Bear Case
3-5 honest, numbered risks. Include execution risk, macro, balance-sheet concerns, valuation stretch.

## 4. Valuation
Compare current multiples to typical sector ranges and the company's own history. Run a quick sanity check (e.g. "at X forward P/E vs sector at Y, the stock prices in Z% growth").

## 5. Technical Picture
Trend (above/below 50d & 200d MA), momentum (RSI), key levels (52-week range). End with a one-word signal: **Bullish / Bearish / Neutral**.

## 6. Verdict
- **Rating:** Strong Buy / Buy / Hold / Sell / Strong Sell
- **Conviction:** High / Medium / Low
- One-paragraph synthesis.
- **Bull-flip trigger:** what would make you more positive.
- **Bear-flip trigger:** what would make you more negative.
- **One thing to watch:** the single most important variable.

Keep it tight. No fluff."""


SCREENER_PROMPT = """You are an investment research analyst reviewing two market screens.

You will see two ranked tables:
  A) HIGH RISK / HIGH REWARD — small-to-mid cap growth names ranked by revenue & earnings growth
  B) SAFE & SOLID            — large cap quality ranked by value + steady growth

Your task:
1. Pick your 2 best ideas from each category (4 total) — be specific about the set-up NOW
2. Name one single Best Idea across both lists with a conviction call
3. In each pick: ticker + one-line thesis + 2 sentences (why now, key risk)

OUTPUT FORMAT:

## ⚡ High Risk Picks
### [TICKER] — [one-line thesis]
[2 sentences]

### [TICKER] — [one-line thesis]
[2 sentences]

## 🛡️ Safe Picks
### [TICKER] — [one-line thesis]
[2 sentences]

### [TICKER] — [one-line thesis]
[2 sentences]

## 🏆 Best Idea: [TICKER]
**Conviction: High / Medium / Low** | **Category: High Risk / Safe**
[2 sentences of conviction — why this beats everything else on both lists]

Be direct. Reference the actual numbers. No boilerplate."""


def stream_screener_insights(high_risk: list, safe: list) -> Iterator[str]:
    """Stream Claude's top-picks commentary from the two screener buckets."""
    def _row(rank: int, r) -> str:
        pe  = f"{r.pe_forward:.1f}×"         if r.pe_forward   is not None else "n/a"
        eg  = f"{r.eps_growth*100:+.1f}%"    if r.eps_growth   is not None else "n/a"
        w52 = f"{r.week52_chg*100:+.1f}%"    if r.week52_chg   is not None else "n/a"
        ma  = f"{r.vs_ma200*100:+.1f}%"      if r.vs_ma200     is not None else "n/a"
        mc  = f"${r.market_cap/1e9:.1f}B"    if r.market_cap   is not None else "n/a"
        return f"{rank} | {r.symbol} | {r.name[:28]} | {mc} | {eg} | {pe} | {w52} | {ma} | {r.score:.0f}"

    hr_lines = [
        "Rank | Ticker | Name | Mkt Cap | EPS Growth | Fwd P/E | 52w | vs200MA | Score",
        "---|---|---|---|---|---|---|---|---",
    ] + [_row(i+1, r) for i, r in enumerate(high_risk[:15])]

    sf_lines = [
        "Rank | Ticker | Name | Mkt Cap | EPS Growth | Fwd P/E | 52w | vs200MA | Score",
        "---|---|---|---|---|---|---|---|---",
    ] + [_row(i+1, r) for i, r in enumerate(safe[:15])]

    user_msg = (
        "**HIGH RISK / HIGH REWARD screen (top 15):**\n"
        + "\n".join(hr_lines)
        + "\n\n**SAFE & SOLID screen (top 15):**\n"
        + "\n".join(sf_lines)
        + "\n\nGive me your top picks from both lists."
    )

    client = Anthropic(api_key=_api_key() or None)
    with client.messages.stream(
        model=MODEL,
        max_tokens=2000,
        system=[{"type": "text", "text": SCREENER_PROMPT, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user_msg}],
    ) as stream:
        for text in stream.text_stream:
            yield text


def stream_report(snapshot: Snapshot) -> Iterator[str]:
    client = Anthropic(api_key=_api_key() or None)
    user_msg = (
        f"Analyse {snapshot.ticker}.\n\n"
        f"Current snapshot:\n\n{snapshot_to_markdown(snapshot)}\n\n"
        "Produce the full structured report."
    )

    with client.messages.stream(
        model=MODEL,
        max_tokens=4000,
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": user_msg}],
    ) as stream:
        for text in stream.text_stream:
            yield text
