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
