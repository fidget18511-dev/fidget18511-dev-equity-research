"""Streamlit dashboard — ticker in, full analyst report out."""
import hmac
import os

import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

from analyst import stream_report
from data import fetch_snapshot

load_dotenv(override=True)

st.set_page_config(
    page_title="Equity Research",
    layout="wide",
    page_icon="📈",
    initial_sidebar_state="expanded",
)


def _gate() -> bool:
    """If SHARE_PASSWORD (env var or Streamlit secret) is set, require it."""
    expected = os.environ.get("SHARE_PASSWORD", "")
    if not expected:
        try:
            expected = st.secrets.get("SHARE_PASSWORD", "")
        except Exception:
            expected = ""
    if not expected:
        return True
    if st.session_state.get("authed"):
        return True

    st.markdown(
        """
<style>
.gate-wrap { max-width: 380px; margin: 6rem auto 0; text-align: center; }
.gate-title { font-size: 1.6rem; font-weight: 600; color: #f4f5f7; margin-bottom: 0.25rem; }
.gate-sub { color: #6b7280; font-size: 0.95rem; margin-bottom: 1.75rem; }
</style>
<div class="gate-wrap">
  <div class="gate-title">📈 Equity Research</div>
  <div class="gate-sub">Enter the access password to continue.</div>
</div>
""",
        unsafe_allow_html=True,
    )
    _, mid, _ = st.columns([1, 2, 1])
    with mid:
        pw = st.text_input("Password", type="password", label_visibility="collapsed", placeholder="Password")
        if st.button("Enter", type="primary", use_container_width=True):
            if hmac.compare_digest(pw, expected):
                st.session_state.authed = True
                st.rerun()
            else:
                st.error("Wrong password.")
    return False


if not _gate():
    st.stop()

st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

html, body, [class*="css"] { font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif; }

.main .block-container { padding-top: 2.5rem; padding-bottom: 4rem; max-width: 1400px; }

[data-testid="stSidebar"] { background-color: #0b0e13; border-right: 1px solid #1f242e; }
[data-testid="stSidebar"] .stTextInput input {
    background-color: #151921; border: 1px solid #232936; color: #e8eaed;
    font-family: 'JetBrains Mono', monospace; font-size: 1.1rem;
    letter-spacing: 0.08em; text-transform: uppercase; font-weight: 500;
}
[data-testid="stSidebar"] .stTextInput input:focus { border-color: #00d68f; box-shadow: 0 0 0 1px #00d68f33; }

[data-testid="stMetric"] {
    background: linear-gradient(180deg, #151921 0%, #11141a 100%);
    border: 1px solid #1f242e;
    border-radius: 10px;
    padding: 14px 18px;
    transition: border-color 0.15s;
}
[data-testid="stMetric"]:hover { border-color: #2a3142; }
[data-testid="stMetricLabel"] {
    color: #6b7280 !important;
    font-size: 0.72rem !important;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    font-weight: 500;
}
[data-testid="stMetricValue"] {
    font-size: 1.5rem !important;
    font-weight: 600 !important;
    font-family: 'JetBrains Mono', monospace !important;
    letter-spacing: -0.02em;
    color: #f4f5f7 !important;
}
[data-testid="stMetricDelta"] { font-family: 'JetBrains Mono', monospace !important; font-size: 0.85rem !important; }

.ticker-header { display: flex; align-items: baseline; gap: 0.9rem; margin: 0 0 0.15rem 0; }
.ticker-symbol {
    font-family: 'JetBrains Mono', monospace;
    font-size: 2.4rem;
    font-weight: 700;
    letter-spacing: -0.03em;
    color: #f4f5f7;
}
.ticker-name { color: #9ca3af; font-size: 1.1rem; font-weight: 400; }
.ticker-meta { color: #6b7280; font-size: 0.85rem; margin-bottom: 1.75rem; letter-spacing: 0.02em; }

.section-label {
    color: #6b7280; font-size: 0.72rem; letter-spacing: 0.12em;
    text-transform: uppercase; font-weight: 500; margin: 0 0 0.85rem 0;
}

hr { margin: 2rem 0 !important; border: none !important; border-top: 1px solid #1f242e !important; }

.stButton button[kind="primary"] {
    background: linear-gradient(180deg, #00d68f 0%, #00a872 100%);
    border: none; color: #062a1d; font-weight: 600; letter-spacing: 0.02em;
    box-shadow: 0 1px 0 rgba(255,255,255,0.1) inset, 0 1px 3px rgba(0,0,0,0.3);
    transition: transform 0.05s, box-shadow 0.15s;
}
.stButton button[kind="primary"]:hover {
    background: linear-gradient(180deg, #00e89c 0%, #00b87d 100%);
    box-shadow: 0 1px 0 rgba(255,255,255,0.15) inset, 0 2px 8px rgba(0,214,143,0.3);
}
.stButton button[kind="primary"]:active { transform: translateY(1px); }

h1, h2, h3 { font-weight: 600; letter-spacing: -0.02em; color: #f4f5f7; }
h2 { font-size: 1.35rem; margin-top: 0; }

.stAlert { border-radius: 8px; }

.report-container {
    background: #11141a; border: 1px solid #1f242e; border-radius: 10px;
    padding: 1.5rem 2rem;
}
.report-container h2 { font-size: 1.1rem; color: #00d68f; margin-top: 1.5rem; }
.report-container h2:first-child { margin-top: 0; }
.report-container strong { color: #f4f5f7; }
</style>
""",
    unsafe_allow_html=True,
)

with st.sidebar:
    st.markdown("### Equity Research")
    st.caption("Data-driven analyst, on demand")
    st.markdown("")
    ticker = st.text_input("Ticker", value="AAPL", placeholder="AAPL").strip().upper()
    run = st.button("Analyse", type="primary", use_container_width=True)
    st.markdown("---")
    st.caption("Data · Yahoo Finance")
    st.caption("Analyst · Claude Sonnet 4.6")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        st.warning("ANTHROPIC_API_KEY not set", icon="⚠️")

if not run:
    st.markdown("# Equity Research")
    st.markdown(
        "<div style='color:#6b7280; font-size:1.05rem; margin-top:-0.5rem;'>"
        "Enter a ticker in the sidebar to begin.</div>",
        unsafe_allow_html=True,
    )
    st.stop()

with st.spinner(f"Fetching {ticker}…"):
    try:
        snap, hist = fetch_snapshot(ticker)
    except Exception as e:
        st.error(f"Could not fetch data for {ticker}: {e}")
        st.stop()


def _mc(v):
    if v is None:
        return "—"
    if v >= 1e12:
        return f"${v/1e12:.2f}T"
    if v >= 1e9:
        return f"${v/1e9:.2f}B"
    if v >= 1e6:
        return f"${v/1e6:.2f}M"
    return f"${v:,.0f}"


def _pct(v):
    return "—" if v is None else f"{v*100:.1f}%"


def _pct_raw(v):
    return "—" if v is None else f"{v:+.1f}%"


def _num(v):
    return "—" if v is None else f"{v:.2f}"


close = hist["Close"]
day_change_pct = float((close.iloc[-1] / close.iloc[-2] - 1) * 100) if len(close) > 1 else 0.0

st.markdown(
    f"""
<div class="ticker-header">
  <div class="ticker-symbol">{snap.ticker}</div>
  <div class="ticker-name">{snap.name or ''}</div>
</div>
<div class="ticker-meta">{snap.sector or '—'} · {snap.industry or '—'} · 52w range
{f'${snap.week52_low:,.2f} – ${snap.week52_high:,.2f}' if snap.week52_low and snap.week52_high else '—'}</div>
""",
    unsafe_allow_html=True,
)

st.markdown('<div class="section-label">Valuation</div>', unsafe_allow_html=True)
c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("Price", f"${snap.price:,.2f}", f"{day_change_pct:+.2f}%")
c2.metric("Market Cap", _mc(snap.market_cap))
c3.metric("P/E TTM", _num(snap.pe_ttm))
c4.metric("Forward P/E", _num(snap.pe_forward))
c5.metric("EV/EBITDA", _num(snap.ev_ebitda))
c6.metric("P/FCF", _num(snap.p_fcf))

st.markdown('<div class="section-label" style="margin-top:1.25rem;">Quality & Technicals</div>', unsafe_allow_html=True)
c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("Revenue Growth", _pct(snap.revenue_growth_yoy))
c2.metric("EBITDA Margin", _pct(snap.ebitda_margin))
c3.metric("Net Debt/EBITDA", _num(snap.net_debt_to_ebitda))
c4.metric("Short Interest", _pct(snap.short_pct_float))
c5.metric("RSI (14)", _num(snap.rsi_14))
c6.metric("vs 200d MA", _pct_raw(snap.vs_ma_200_pct))

st.markdown("---")

st.markdown('<div class="section-label">Price · 2 years</div>', unsafe_allow_html=True)
ma50 = close.rolling(50).mean()
ma200 = close.rolling(200).mean()

fig = go.Figure()
fig.add_trace(
    go.Scatter(
        x=close.index, y=close, name="Close",
        line=dict(width=2, color="#00d68f"),
        hovertemplate="%{y:$,.2f}<extra></extra>",
    )
)
fig.add_trace(
    go.Scatter(
        x=close.index, y=ma50, name="50-day MA",
        line=dict(width=1.2, color="#7d8da0"),
        hovertemplate="%{y:$,.2f}<extra></extra>",
    )
)
fig.add_trace(
    go.Scatter(
        x=close.index, y=ma200, name="200-day MA",
        line=dict(width=1.2, color="#4a5468", dash="dash"),
        hovertemplate="%{y:$,.2f}<extra></extra>",
    )
)
fig.update_layout(
    template="plotly_dark",
    height=440,
    margin=dict(l=10, r=10, t=10, b=10),
    paper_bgcolor="#0b0e13",
    plot_bgcolor="#0b0e13",
    xaxis=dict(showgrid=False, title=None, color="#6b7280"),
    yaxis=dict(
        showgrid=True, gridcolor="#1f242e", title=None,
        color="#6b7280", tickprefix="$", side="right",
    ),
    legend=dict(orientation="h", y=1.08, x=0, bgcolor="rgba(0,0,0,0)", font=dict(color="#9ca3af")),
    hovermode="x unified",
    hoverlabel=dict(bgcolor="#151921", bordercolor="#2a3142", font=dict(family="JetBrains Mono")),
)
st.plotly_chart(fig, use_container_width=True)

st.markdown("---")
st.markdown('<div class="section-label">Analyst Report</div>', unsafe_allow_html=True)

st.markdown('<div class="report-container">', unsafe_allow_html=True)
report_box = st.empty()
chunks: list[str] = []
try:
    for chunk in stream_report(snap):
        chunks.append(chunk)
        report_box.markdown("".join(chunks))
except Exception as e:
    st.error(f"Claude API error: {e}")
st.markdown("</div>", unsafe_allow_html=True)
