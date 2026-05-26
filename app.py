"""Streamlit dashboard — ticker in, full analyst report out. Tab 2: stock screener."""
import hmac
import os

import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

from analyst import stream_report, stream_screener_insights
from data import fetch_snapshot
from screener import render_table, run_screen

load_dotenv(override=True)

st.set_page_config(
    page_title="Equity Research",
    layout="wide",
    page_icon="📈",
    initial_sidebar_state="expanded",
)


# ── Password gate ──────────────────────────────────────────────────────────────
def _gate() -> bool:
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


# ── Global CSS ────────────────────────────────────────────────────────────────
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

/* ── Screener table ── */
.screener-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.88rem;
}
.screener-table th {
    color: #6b7280;
    font-size: 0.68rem;
    letter-spacing: 0.09em;
    text-transform: uppercase;
    font-weight: 500;
    padding: 9px 14px;
    border-bottom: 1px solid #1f242e;
    text-align: left;
    white-space: nowrap;
    background: #0b0e13;
    position: sticky;
    top: 0;
}
.screener-table td {
    padding: 9px 14px;
    border-bottom: 1px solid #0d1017;
    vertical-align: middle;
}
.screener-table tbody tr:hover td { background: rgba(255,255,255,0.025); }

.cell-green { color: #00d68f; }
.cell-amber { color: #f59e0b; }
.cell-red   { color: #ef4444; }
.cell-dim   { color: #374151; }

/* ── Pick cards ── */
.pick-card {
    background: #0f1218;
    border: 1px solid #1f242e;
    border-radius: 12px;
    padding: 18px 20px;
    height: 100%;
    transition: border-color 0.2s, background 0.2s;
}
.pick-card:hover { border-color: #2d3748; background: #111520; }
.pick-rank-badge {
    display: inline-block;
    font-size: 0.68rem;
    font-weight: 600;
    letter-spacing: 0.09em;
    text-transform: uppercase;
    padding: 2px 9px;
    border-radius: 20px;
    margin-bottom: 10px;
}
.pick-ticker { font-family: 'JetBrains Mono', monospace; font-size: 2rem; font-weight: 700; color: #f4f5f7; line-height: 1.1; }
.pick-name { color: #6b7280; font-size: 0.8rem; margin-top: 2px; margin-bottom: 14px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.pick-score-line { display: flex; align-items: center; gap: 8px; margin-bottom: 14px; }
.pick-score-bar-bg { flex: 1; height: 4px; background: #1f242e; border-radius: 3px; }
.pick-score-bar-fill { height: 4px; border-radius: 3px; }
.pick-score-num { font-family: 'JetBrains Mono', monospace; font-size: 0.82rem; font-weight: 700; }
.pick-stats { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.pick-stat { }
.pick-stat-label { color: #4b5563; font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.06em; }
.pick-stat-val { color: #d1d5db; font-family: 'JetBrains Mono', monospace; font-size: 0.85rem; font-weight: 500; margin-top: 1px; }

/* ── Section divider ── */
.scr-section {
    display: flex;
    align-items: center;
    gap: 14px;
    margin: 28px 0 18px;
}
.scr-section-icon { font-size: 1.3rem; line-height: 1; }
.scr-section-label { font-size: 0.68rem; font-weight: 600; letter-spacing: 0.12em; text-transform: uppercase; }
.scr-section-title { font-size: 1.1rem; font-weight: 700; color: #f4f5f7; margin-top: 1px; }
.scr-section-line { flex: 1; height: 1px; background: #1f242e; }

/* ── Table wrapper (scrollable) ── */
.scr-table-wrap {
    background: #0b0e13;
    border: 1px solid #1f242e;
    border-radius: 10px;
    overflow: hidden;
    max-height: 560px;
    overflow-y: auto;
}
</style>
""",
    unsafe_allow_html=True,
)


# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### Equity Research")
    st.caption("Data-driven analysis, on demand")
    st.markdown("")
    ticker = st.text_input("Ticker", value="AAPL", placeholder="AAPL").strip().upper()
    run = st.button("Analyse", type="primary", use_container_width=True)
    st.markdown("---")
    st.caption("Data · Yahoo Finance")
    st.caption("Analyst · Claude Sonnet 4.6")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        st.warning("ANTHROPIC_API_KEY not set", icon="⚠️")


# ── Tabs ───────────────────────────────────────────────────────────────────────
tab_res, tab_scr = st.tabs(["🔍  Research", "📊  Screener"])


# ════════════════════════════════════════════════════════════════════════════════
# TAB 1 — RESEARCH
# ════════════════════════════════════════════════════════════════════════════════
with tab_res:
    if not run:
        st.markdown("# Equity Research")
        st.markdown(
            "<div style='color:#6b7280; font-size:1.05rem; margin-top:-0.5rem;'>"
            "Enter a ticker in the sidebar and click <strong>Analyse</strong>.</div>",
            unsafe_allow_html=True,
        )
    else:
        snap = None
        hist = None
        with st.spinner(f"Fetching {ticker}…"):
            try:
                snap, hist = fetch_snapshot(ticker)
            except Exception as e:
                st.error(f"Could not fetch data for **{ticker}**: {e}")

        if snap is not None:
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
<div class="ticker-meta">
  {snap.sector or '—'} · {snap.industry or '—'} · 52w range
  {f'${snap.week52_low:,.2f} – ${snap.week52_high:,.2f}' if snap.week52_low and snap.week52_high else '—'}
</div>
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
            ma50  = close.rolling(50).mean()
            ma200 = close.rolling(200).mean()

            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=close.index, y=close, name="Close",
                line=dict(width=2, color="#00d68f"),
                hovertemplate="%{y:$,.2f}<extra></extra>",
            ))
            fig.add_trace(go.Scatter(
                x=close.index, y=ma50, name="50d MA",
                line=dict(width=1.2, color="#7d8da0"),
                hovertemplate="%{y:$,.2f}<extra></extra>",
            ))
            fig.add_trace(go.Scatter(
                x=close.index, y=ma200, name="200d MA",
                line=dict(width=1.2, color="#4a5468", dash="dash"),
                hovertemplate="%{y:$,.2f}<extra></extra>",
            ))
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


# ════════════════════════════════════════════════════════════════════════════════
# TAB 2 — SCREENER
# ════════════════════════════════════════════════════════════════════════════════
# TAB 2 — SCREENER
# ════════════════════════════════════════════════════════════════════════════════
with tab_scr:

    # ── Header row ────────────────────────────────────────────────────────────
    hd_l, hd_r = st.columns([5, 1])
    with hd_l:
        st.markdown("## Market Screener")
        st.markdown(
            "<div style='color:#6b7280;margin-top:-0.4rem;font-size:0.92rem'>"
            "Live market-wide screen · two buckets: high risk/reward and safe high-potential."
            "</div>",
            unsafe_allow_html=True,
        )
    with hd_r:
        btn_run = st.button("Run Screen", type="primary", use_container_width=True, key="run_screen")

    # ── Run the screen ────────────────────────────────────────────────────────
    if btn_run:
        prog = st.progress(0.0, text="Pulling screener data…")

        def _scr_cb(pct: float) -> None:
            prog.progress(pct, text=f"Fetching… {int(pct * 100)}%")

        hr, sf = run_screen(progress_cb=_scr_cb)
        prog.empty()
        st.session_state.scr_hr       = hr
        st.session_state.scr_sf       = sf
        st.session_state.scr_insights = None

    hr: list = st.session_state.get("scr_hr", [])
    sf: list = st.session_state.get("scr_sf", [])

    # ── Empty state ───────────────────────────────────────────────────────────
    if not hr and not sf:
        st.markdown("""
<div style="margin:3rem auto;max-width:540px;text-align:center">
  <div style="font-size:2.5rem;margin-bottom:1rem">📡</div>
  <div style="color:#f4f5f7;font-size:1.1rem;font-weight:600;margin-bottom:0.5rem">Hit Run Screen to start</div>
  <div style="color:#6b7280;font-size:0.9rem">
    Queries Yahoo Finance's live market screener across hundreds of US stocks.<br>
    Results split into <strong style="color:#f97316">High Risk / High Reward</strong>
    and <strong style="color:#00d68f">Safe &amp; Solid</strong> buckets.<br>
    Takes ~5 seconds.
  </div>
</div>""", unsafe_allow_html=True)

    else:
        # ── Helper: render pick cards for top N from a list ───────────────────
        def _pick_cards(rows: list, accent: str, n: int = 3) -> None:
            top = rows[:n]
            cols = st.columns(n)
            ranks = ["#1", "#2", "#3"]
            for col, r, rank in zip(cols, top, ranks):
                pe_s  = f"{r.pe_forward:.1f}×"        if r.pe_forward  is not None else "—"
                rg_s  = f"{r.eps_growth*100:+.1f}%"   if r.eps_growth  is not None else "—"
                eg_s  = f"{r.vs_ma200*100:+.1f}%"     if r.vs_ma200    is not None else "—"
                w52_s = f"{r.week52_chg*100:+.1f}%"   if r.week52_chg  is not None else "—"
                bar_w = min(100, max(0, r.score))
                name_s = r.name[:34] + "…" if len(r.name) > 34 else r.name

                with col:
                    st.markdown(f"""
<div class="pick-card">
  <div>
    <span class="pick-rank-badge" style="background:rgba(255,255,255,0.06);color:{accent}">{rank} Pick</span>
  </div>
  <div class="pick-ticker">{r.symbol}</div>
  <div class="pick-name">{name_s}</div>
  <div class="pick-score-line">
    <div class="pick-score-bar-bg">
      <div class="pick-score-bar-fill" style="width:{bar_w:.0f}%;background:{accent}"></div>
    </div>
    <span class="pick-score-num" style="color:{accent}">{r.score:.0f}</span>
  </div>
  <div class="pick-stats">
    <div class="pick-stat">
      <div class="pick-stat-label">EPS Growth</div>
      <div class="pick-stat-val">{rg_s}</div>
    </div>
    <div class="pick-stat">
      <div class="pick-stat-label">vs 200MA</div>
      <div class="pick-stat-val">{eg_s}</div>
    </div>
    <div class="pick-stat">
      <div class="pick-stat-label">Fwd P/E</div>
      <div class="pick-stat-val">{pe_s}</div>
    </div>
    <div class="pick-stat">
      <div class="pick-stat-label">52-week</div>
      <div class="pick-stat-val">{w52_s}</div>
    </div>
  </div>
</div>""", unsafe_allow_html=True)

        # ── HIGH RISK / HIGH REWARD ───────────────────────────────────────────
        if hr:
            st.markdown("""
<div class="scr-section">
  <div class="scr-section-icon">⚡</div>
  <div>
    <div class="scr-section-label" style="color:#f97316">High Risk</div>
    <div class="scr-section-title">High Reward</div>
  </div>
  <div class="scr-section-line"></div>
  <div style="color:#6b7280;font-size:0.8rem;white-space:nowrap">small &amp; mid cap · growth momentum</div>
</div>""", unsafe_allow_html=True)

            _pick_cards(hr, accent="#f97316")
            st.markdown(
                '<div class="scr-table-wrap">' + render_table(hr, accent="#f97316") + "</div>",
                unsafe_allow_html=True,
            )

        # ── SAFE & SOLID ──────────────────────────────────────────────────────
        if sf:
            st.markdown("""
<div class="scr-section">
  <div class="scr-section-icon">🛡️</div>
  <div>
    <div class="scr-section-label" style="color:#00d68f">Safe &amp; Solid</div>
    <div class="scr-section-title">High Potential</div>
  </div>
  <div class="scr-section-line"></div>
  <div style="color:#6b7280;font-size:0.8rem;white-space:nowrap">large cap · quality + value</div>
</div>""", unsafe_allow_html=True)

            _pick_cards(sf, accent="#00d68f")
            st.markdown(
                '<div class="scr-table-wrap">' + render_table(sf, accent="#00d68f") + "</div>",
                unsafe_allow_html=True,
            )

        # ── AI Insights ───────────────────────────────────────────────────────
        st.markdown("---")
        st.markdown('<div class="section-label">AI Insights</div>', unsafe_allow_html=True)

        if st.button("✨ Generate AI Insights", type="primary", key="gen_insights"):
            st.markdown('<div class="report-container">', unsafe_allow_html=True)
            ins_box    = st.empty()
            ins_chunks: list[str] = []
            try:
                for chunk in stream_screener_insights(hr, sf):
                    ins_chunks.append(chunk)
                    ins_box.markdown("".join(ins_chunks))
            except Exception as e:
                st.error(f"Claude API error: {e}")
            st.session_state.scr_insights = "".join(ins_chunks)
            st.markdown("</div>", unsafe_allow_html=True)

        elif st.session_state.get("scr_insights"):
            st.markdown('<div class="report-container">', unsafe_allow_html=True)
            st.markdown(st.session_state.scr_insights)
            st.markdown("</div>", unsafe_allow_html=True)
        else:
            st.markdown(
                "<div style='color:#4b5563;font-size:0.85rem;margin-top:0.5rem'>"
                "Run the screen first, then click above to get Claude's top picks from both lists."
                "</div>",
                unsafe_allow_html=True,
            )
