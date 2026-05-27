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

SYSTEM_PROMPT = """You are a blunt, experienced investment research analyst — think senior PM at a hedge fund. Your job is to give a real view, not a comfortable one.

CORE BEHAVIOUR
- Be direct to the point of being uncomfortable. If a stock is overvalued or has a bad setup, say so clearly.
- Challenge the premise. If someone is looking at a stock with deteriorating fundamentals or a narrative-driven valuation, call it out.
- Don't validate bad ideas. If the data doesn't support the bull case, say the bull case is weak.
- Use the figures provided. Do not invent numbers. If marked n/a, say so.
- No disclaimers, no "it depends", no sitting on the fence.
- A "Hold" is often just a polite "don't buy this". Say what you actually mean.

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


SCREENER_PROMPT = """You are a blunt, experienced portfolio manager reviewing three stock screens. Your job is to cut through the noise.

RULES:
- Be opinionated. Wrong and confident beats right and wishy-washy.
- If a top-ranked stock is actually a bad idea (cyclical spike, already played out, terrible setup), say so — and pick something lower on the list instead.
- Call out any obvious red flags in the data (e.g. 500% 52w gain = upside already captured, low PE on a cyclical = earnings at peak).
- For dip picks: your #1 job is to tell the difference between "the market overreacted and you should buy" vs "this is a falling knife and you'll regret it". A stock down 5% with broken trend and declining earnings is NOT a buying opportunity. Say so.
- If the user is looking at garbage, tell them it's garbage.
- Reference actual numbers. No vague statements.

You will see THREE ranked tables:
  A) HIGH RISK / HIGH REWARD — small/mid cap growth names
  B) SAFE & SOLID            — large cap quality + value
  C) TODAY'S DIPS            — stocks down today; score reflects trend health + fundamentals

Your output:

## ⚡ High Risk Picks
### [TICKER] — [one-line thesis]
[2 sentences: the specific set-up, why NOW, and the real risk that could kill the trade]

### [TICKER] — [one-line thesis]
[2 sentences]

## 🛡️ Safe Picks
### [TICKER] — [one-line thesis]
[2 sentences]

### [TICKER] — [one-line thesis]
[2 sentences]

## 🎯 Dip Buys
### [TICKER] — [buy the dip or falling knife?]
[2 sentences: what makes today's drop a buying opportunity. Reference the 200MA, 52w context, and EPS trajectory. If it's a knife, call it.]

### [TICKER] — [same]

## 🏆 Best Idea: [TICKER]
**Conviction: High / Medium / Low** | **Category: High Risk / Safe / Dip**
[2 sentences — why this beats everything else on the screen right now]

## ⚠️ Avoid / Overrated
- **[TICKER]**: [one sentence on why the ranking is misleading or the setup is poor]
- **[TICKER]**: [same]

Be ruthless. The user can handle the truth."""


def stream_screener_insights(high_risk: list, safe: list, dips: list | None = None) -> Iterator[str]:
    """Stream Claude's top-picks commentary from all screener buckets."""
    def _row(rank: int, r) -> str:
        pe  = f"{r.pe_forward:.1f}×"         if r.pe_forward   is not None else "n/a"
        eg  = f"{r.eps_growth*100:+.1f}%"    if r.eps_growth   is not None else "n/a"
        w52 = f"{r.week52_chg*100:+.1f}%"    if r.week52_chg   is not None else "n/a"
        ma  = f"{r.vs_ma200*100:+.1f}%"      if r.vs_ma200     is not None else "n/a"
        mc  = f"${r.market_cap/1e9:.1f}B"    if r.market_cap   is not None else "n/a"
        return f"{rank} | {r.symbol} | {r.name[:28]} | {mc} | {eg} | {pe} | {w52} | {ma} | {r.score:.0f}"

    def _dip_row(rank: int, r) -> str:
        pe  = f"{r.pe_forward:.1f}×"         if r.pe_forward   is not None else "n/a"
        eg  = f"{r.eps_growth*100:+.1f}%"    if r.eps_growth   is not None else "n/a"
        w52 = f"{r.week52_chg*100:+.1f}%"    if r.week52_chg   is not None else "n/a"
        ma  = f"{r.vs_ma200*100:+.1f}%"      if r.vs_ma200     is not None else "n/a"
        mc  = f"${r.market_cap/1e9:.1f}B"    if r.market_cap   is not None else "n/a"
        day = f"{r.day_chg*100:+.1f}%"       if r.day_chg      is not None else "n/a"
        return f"{rank} | {r.symbol} | {r.name[:28]} | {mc} | {day} | {eg} | {pe} | {w52} | {ma} | {r.score:.0f}"

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
    )

    if dips:
        dp_lines = [
            "Rank | Ticker | Name | Mkt Cap | Today | EPS Growth | Fwd P/E | 52w | vs200MA | Score",
            "---|---|---|---|---|---|---|---|---|---",
        ] + [_dip_row(i+1, r) for i, r in enumerate(dips[:15])]
        user_msg += (
            "\n\n**TODAY'S DIPS screen (top 15 — stocks down today with quality fundamentals):**\n"
            + "\n".join(dp_lines)
        )

    user_msg += "\n\nGive me your top picks from all lists."

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
