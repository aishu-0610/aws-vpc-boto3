"""
pages/2_Analytics.py  —  FocusGate Analytics Dashboard
Developer B owns this file.

Charts:
  - Focus score gauge (Plotly indicator)
  - Week-over-week trend card + details
  - Distraction heatmap (hour × weekday density)
  - Daily query trend (total vs blocked area chart)
  - Category breakdown (donut)
  - Top distraction domains (bar + table)
  - Latency stats (p50/p95/p99)
"""

import httpx
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

API = "http://localhost:8000"

st.set_page_config(
    page_title="Analytics · FocusGate",
    page_icon="📊",
    layout="wide",
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&family=DM+Sans:wght@300;400;500;600&display=swap');
html, body, [class*="css"] { font-family: 'DM Sans', sans-serif; }

.stat-card {
    background: linear-gradient(145deg,#10102a,#0c1820);
    border: 1px solid rgba(100,100,200,0.18);
    border-radius: 14px;
    padding: 1.4rem;
    text-align: center;
}
.stat-val  { font-family:'JetBrains Mono',monospace; font-size:2rem; font-weight:700; }
.stat-lbl  { font-size:0.72rem; color:#5558aa; text-transform:uppercase; letter-spacing:1px; margin-top:4px; }

.score-wrap { display:flex; flex-direction:column; align-items:center; justify-content:center; min-height:220px; }
.score-num  { font-family:'JetBrains Mono',monospace; font-size:4rem; font-weight:700; }
.score-lbl  { font-size:0.8rem; color:#5558aa; letter-spacing:1px; text-transform:uppercase; }

.lat-card {
    background:#09091a;
    border:1px solid #1a1a3a;
    border-radius:10px;
    padding:1rem;
    text-align:center;
}
</style>
""", unsafe_allow_html=True)

# ── Dark Plotly theme ──────────────────────────────────────────────────
DARK = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(10,10,26,0.9)",
    font=dict(family="DM Sans, sans-serif", color="#9090c0"),
    title_font=dict(color="#c0c0e0"),
    xaxis=dict(gridcolor="#1a1a3a", linecolor="#1a1a3a", zeroline=False),
    yaxis=dict(gridcolor="#1a1a3a", linecolor="#1a1a3a", zeroline=False),
    margin=dict(t=30, b=40, l=30, r=20),
)

WEEKDAY_ORDER = ["Monday","Tuesday","Wednesday",
                 "Thursday","Friday","Saturday","Sunday"]

# ── Data loading ───────────────────────────────────────────────────────

def load(path, params=None):
    try:
        r = httpx.get(f"{API}{path}", params=params or {}, timeout=5)
        return r.json()
    except Exception:
        return None


st.title("📊 Behavioral Analytics")

top_row = st.columns([2, 1])
with top_row[0]:
    days = st.select_slider(
        "Time window",
        options=[3, 7, 14, 30],
        value=7,
        format_func=lambda d: f"Last {d} days",
    )
with top_row[1]:
    if st.button("🔄 Refresh all", use_container_width=True):
        st.cache_data.clear()

p = {"days": days}

@st.cache_data(ttl=60)
def all_data(d):
    return {
        "summary":  load("/analytics/summary",    {"days": d}),
        "score":    load("/analytics/focus-score", {"days": d}),
        "heatmap":  load("/analytics/heatmap",    {"days": d}),
        "trend":    load("/analytics/trend",       {"days": d}),
        "cats":     load("/analytics/categories",  {"days": d}),
        "top":      load("/analytics/top-domains", {"days": d, "limit": 15}),
        "latency":  load("/analytics/latency",     {"days": d}),
    }

data = all_data(days)

summary = data["summary"] or {}
score   = data["score"]   or {}
sc_val  = score.get("score", 0)
trend   = score.get("trend", "stable")

# ── Section 1: Score row ───────────────────────────────────────────────
st.markdown("---")
sc1, sc2, sc3, sc4, sc5 = st.columns(5)

sc_color = "#4ade80" if sc_val >= 70 else "#facc15" if sc_val >= 40 else "#f87171"
t_icon   = {"improving":"↑ Improving","worsening":"↓ Worsening","stable":"→ Stable"}

with sc1:
    st.markdown(f"""
    <div class="stat-card">
      <div class="score-wrap">
        <div class="score-num" style="color:{sc_color}">{sc_val}</div>
        <div class="score-lbl">Focus Score /100</div>
        <div style="color:{sc_color};font-size:0.85rem;margin-top:4px">
          {t_icon.get(trend,'→')}
        </div>
      </div>
    </div>
    """, unsafe_allow_html=True)

metrics = [
    (sc2, summary.get("total",   0),         "#60a5fa", "Total Queries"),
    (sc3, summary.get("blocked", 0),         "#f87171", "Blocked"),
    (sc4, f"{summary.get('block_rate',0)}%", "#facc15", "Block Rate"),
    (sc5, summary.get("sessions", 0),        "#a78bfa", "Sessions"),
]
for col, val, color, label in metrics:
    with col:
        st.markdown(f"""
        <div class="stat-card">
          <div class="score-wrap">
            <div class="stat-val" style="color:{color}">{val:,}" if isinstance(val, int) else f"{val}</div>
            <div class="stat-lbl">{label}</div>
          </div>
        </div>
        """.replace('" if isinstance(val, int) else f"', ''), unsafe_allow_html=True)

# ── Section 2: Heatmap ─────────────────────────────────────────────────
st.markdown("---")
st.subheader("🔥 Distraction Heatmap — when do you reach for blocked sites?")

hdata = data["heatmap"]
if hdata:
    df_h = pd.DataFrame(hdata)
    df_h["weekday"] = pd.Categorical(df_h["weekday"],
                                     categories=WEEKDAY_ORDER, ordered=True)
    df_h = df_h.sort_values(["weekday","hour"])

    fig = go.Figure(go.Heatmap(
        x=df_h["hour"],
        y=df_h["weekday"],
        z=df_h["attempts"],
        colorscale=[
            [0.00, "#09091a"],
            [0.25, "#1e1060"],
            [0.55, "#6b21a8"],
            [0.80, "#dc2626"],
            [1.00, "#fbbf24"],
        ],
        hovertemplate="Hour %{x}:00  |  %{y}  |  %{z} attempts<extra></extra>",
        showscale=True,
        colorbar=dict(
            tickfont=dict(color="#7070a0"),
            outlinecolor="rgba(0,0,0,0)",
        ),
    ))
    fig.update_layout(
        height=320,
        xaxis=dict(
            title="Hour of day",
            tickvals=list(range(0, 24, 3)),
            ticktext=[f"{h:02d}:00" for h in range(0, 24, 3)],
            gridcolor="#1a1a3a",
        ),
        yaxis=dict(title="", gridcolor="#1a1a3a"),
        **{k: v for k, v in DARK.items() if k not in ("xaxis","yaxis")},
    )
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("No blocked-query data yet. Start blocking and come back!")

# ── Section 3: Daily trend ─────────────────────────────────────────────
st.markdown("---")
st.subheader("📈 Daily Query Trend")

tdata = data["trend"]
if tdata:
    df_t = pd.DataFrame(tdata)
    fig  = go.Figure()
    fig.add_trace(go.Scatter(
        x=df_t["date"], y=df_t["total"],
        name="Total",
        line=dict(color="#4f72fe", width=2.5),
        fill="tozeroy",
        fillcolor="rgba(79,114,254,0.08)",
        hovertemplate="%{y:,} total<extra>%{x}</extra>",
    ))
    fig.add_trace(go.Scatter(
        x=df_t["date"], y=df_t["blocked"],
        name="Blocked",
        line=dict(color="#f87171", width=2.5),
        fill="tozeroy",
        fillcolor="rgba(248,113,113,0.08)",
        hovertemplate="%{y:,} blocked<extra>%{x}</extra>",
    ))
    fig.update_layout(
        height=280,
        legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color="#9090c0")),
        **DARK,
    )
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("No trend data available yet.")

# ── Section 4: Category + Top domains ─────────────────────────────────
st.markdown("---")
col_pie, col_bar = st.columns(2)

with col_pie:
    st.subheader("🗂️ Category Breakdown")
    cdata = data["cats"]
    if cdata:
        df_c  = pd.DataFrame(cdata)
        colors = ["#4f72fe","#f87171","#4ade80","#facc15","#a78bfa","#fb923c"]
        fig   = go.Figure(go.Pie(
            labels=df_c["category"],
            values=df_c["attempts"],
            hole=0.50,
            marker=dict(colors=colors[:len(df_c)]),
            textfont=dict(color="#c0c0e0"),
            hovertemplate="%{label}: %{value:,} attempts (%{percent})<extra></extra>",
        ))
        fig.update_layout(
            height=280,
            legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color="#9090c0")),
            **{k: v for k, v in DARK.items() if k != "xaxis" and k != "yaxis"},
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No category data yet.")

with col_bar:
    st.subheader("🎯 Top Distraction Sites")
    tdata2 = data["top"]
    if tdata2:
        df_top = pd.DataFrame(tdata2).head(10)
        fig    = go.Figure(go.Bar(
            x=df_top["attempts"],
            y=df_top["domain"],
            orientation="h",
            marker=dict(
                color=df_top["attempts"],
                colorscale=[[0,"#1e1060"],[0.5,"#7c3aed"],[1,"#f87171"]],
                showscale=False,
            ),
            hovertemplate="%{y}: %{x:,} attempts<extra></extra>",
        ))
        fig.update_layout(
            height=280,
            yaxis=dict(autorange="reversed", gridcolor="#1a1a3a"),
            xaxis=dict(gridcolor="#1a1a3a"),
            **{k: v for k, v in DARK.items() if k not in ("xaxis","yaxis")},
        )
        st.plotly_chart(fig, use_container_width=True)

        st.dataframe(
            df_top.rename(columns={"domain":"Domain","category":"Category","attempts":"Attempts"}),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No distraction domain data yet.")

# ── Section 5: Latency stats ───────────────────────────────────────────
st.markdown("---")
st.subheader("⚡ DNS Latency Stats  (interview talking point)")
st.caption("Blocked queries return NXDOMAIN locally. Allowed queries forward to Cloudflare DoH.")

lat = data["latency"] or {}
overall = lat.get("overall", {})
blocked_l = lat.get("blocked", {})
allowed_l = lat.get("allowed", {})

lc1, lc2, lc3 = st.columns(3)

def lat_card(col, title, stats, color):
    with col:
        st.markdown(f"""
        <div class="lat-card">
            <div style="color:{color};font-weight:600;margin-bottom:0.6rem">{title}</div>
            <table style="width:100%;font-family:'JetBrains Mono',monospace;font-size:0.82rem;color:#9090c0">
                <tr><td>p50</td><td style="text-align:right;color:#c0c0e0">{stats.get('p50',0)} ms</td></tr>
                <tr><td>p95</td><td style="text-align:right;color:#c0c0e0">{stats.get('p95',0)} ms</td></tr>
                <tr><td>p99</td><td style="text-align:right;color:#c0c0e0">{stats.get('p99',0)} ms</td></tr>
                <tr><td>mean</td><td style="text-align:right;color:#c0c0e0">{stats.get('mean',0)} ms</td></tr>
            </table>
        </div>
        """, unsafe_allow_html=True)

lat_card(lc1, "Overall",   overall,   "#60a5fa")
lat_card(lc2, "Blocked ⚡", blocked_l, "#4ade80")
lat_card(lc3, "Allowed 🌐", allowed_l, "#facc15")
