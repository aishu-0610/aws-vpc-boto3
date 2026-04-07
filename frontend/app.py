"""
app.py — FocusGate Streamlit Dashboard
Run: streamlit run frontend/app.py
"""

import os
import time
import sqlite3
from datetime import datetime

import httpx
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go


API = "http://localhost:8000"


# ------------------------------------------------
# Page config
# ------------------------------------------------

st.set_page_config(
    page_title="FocusGate",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ------------------------------------------------
# CSS Styling
# ------------------------------------------------

st.markdown("""
<style>

body {
    background-color: #0f172a;
}

.fg-header {
    background: linear-gradient(135deg,#0a0a1a,#11113a,#0a1f2e);
    border-radius: 15px;
    padding: 30px;
}

.fg-title {
    font-size: 40px;
    font-weight: bold;
    color: #60a5fa;
}

.fg-subtitle {
    color: #94a3b8;
}

.metric-grid {
    display: grid;
    grid-template-columns: repeat(5,1fr);
    gap: 10px;
}

.metric-card {
    background:#1e293b;
    padding:15px;
    border-radius:10px;
    text-align:center;
}

.metric-value {
    font-size:26px;
    font-weight:bold;
}

.metric-label {
    font-size:12px;
    color:#94a3b8;
}

.timer {
    font-size:48px;
    text-align:center;
    font-weight:bold;
}

.dns-line {
    font-family: monospace;
    font-size:12px;
}

.dns-blocked {
    color:#f87171;
}

.dns-allowed {
    color:#4ade80;
}

</style>
""", unsafe_allow_html=True)


# ------------------------------------------------
# API helpers
# ------------------------------------------------

def api_get(path, params=None):

    try:
        r = httpx.get(f"{API}{path}", params=params, timeout=3)
        return r.json()

    except:
        return None


def api_post(path, json=None, params=None):

    try:
        r = httpx.post(f"{API}{path}", json=json, params=params)
        return r.json()

    except:
        return None


# ------------------------------------------------
# Cached fetch
# ------------------------------------------------

@st.cache_data(ttl=5)
def fetch_status():
    return api_get("/status")


@st.cache_data(ttl=30)
def fetch_summary():
    return api_get("/analytics/summary") or {}


@st.cache_data(ttl=30)
def fetch_score():
    return api_get("/analytics/focus-score") or {}


# ------------------------------------------------
# DB path
# ------------------------------------------------

def db_path():

    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "../data/focusgate.db")


# ------------------------------------------------
# Header
# ------------------------------------------------

def render_header(status):

    active = status.get("active_session") if status else None
    blocked = status.get("blocked_count",0) if status else 0

    badge = "🟢 ACTIVE" if active else "⚪ IDLE"

    st.markdown(f"""
    <div class="fg-header">
        <div class="fg-title">🎯 FocusGate</div>
        <div class="fg-subtitle">DNS Productivity Firewall</div>
        <br>
        {badge} · {blocked} domains blocked
    </div>
    """, unsafe_allow_html=True)


# ------------------------------------------------
# Metrics
# ------------------------------------------------

def render_metrics(summary, score):

    total = summary.get("total",0)
    blocked = summary.get("blocked",0)
    rate = summary.get("block_rate",0)
    sessions = summary.get("sessions",0)
    sc = score.get("score",0)

    st.markdown(f"""
    <div class="metric-grid">

    <div class="metric-card">
    <div class="metric-value">{total}</div>
    <div class="metric-label">DNS Queries</div>
    </div>

    <div class="metric-card">
    <div class="metric-value">{blocked}</div>
    <div class="metric-label">Blocked</div>
    </div>

    <div class="metric-card">
    <div class="metric-value">{rate}%</div>
    <div class="metric-label">Block Rate</div>
    </div>

    <div class="metric-card">
    <div class="metric-value">{sc}</div>
    <div class="metric-label">Focus Score</div>
    </div>

    <div class="metric-card">
    <div class="metric-value">{sessions}</div>
    <div class="metric-label">Sessions</div>
    </div>

    </div>
    """, unsafe_allow_html=True)


# ------------------------------------------------
# Session Panel
# ------------------------------------------------

def render_session_panel(status):

    st.subheader("Focus Session")

    session = status.get("active_session") if status else None

    if session:

        rem = session.get("remaining_s",0)
        m,s = divmod(rem,60)

        st.markdown(f'<div class="timer">{m:02d}:{s:02d}</div>',
        unsafe_allow_html=True)

        if st.button("End Session"):
            api_post("/session/end", params={"session_id":session["id"]})
            st.rerun()

    else:

        if st.button("Start 25 min Pomodoro"):

            api_post("/session/start",{
                "type":"pomodoro",
                "duration_minutes":25,
                "blocked_categories":["social","entertainment"],
                "hard_lock":False
            })

            st.rerun()


# ------------------------------------------------
# Live DNS log
# ------------------------------------------------

def render_live_log():

    st.subheader("Live DNS Feed")

    try:

        conn = sqlite3.connect(db_path())

        rows = conn.execute(
        "SELECT ts,domain,blocked FROM dns_queries ORDER BY ts DESC LIMIT 20"
        ).fetchall()

        conn.close()

    except:
        st.warning("Database unavailable")
        return

    for ts,domain,blocked in rows:

        icon = "✗" if blocked else "✓"
        cls = "dns-blocked" if blocked else "dns-allowed"

        st.markdown(
        f'<span class="dns-line {cls}">{icon} {domain}</span>',
        unsafe_allow_html=True)


# ------------------------------------------------
# DNS Chart
# ------------------------------------------------

def render_dns_chart():

    st.subheader("DNS Traffic (24h)")

    try:

        conn = sqlite3.connect(db_path())

        df = pd.read_sql_query(
        "SELECT ts,blocked FROM dns_queries", conn)

        conn.close()

    except:
        st.warning("No data")
        return

    if df.empty:
        st.caption("No traffic yet")
        return

    df["ts"]=pd.to_datetime(df["ts"])
    df["hour"]=df["ts"].dt.hour

    traffic=df.groupby(["hour","blocked"]).size().reset_index(name="count")

    fig=px.bar(traffic,x="hour",y="count",color="blocked")

    st.plotly_chart(fig,use_container_width=True)


# ------------------------------------------------
# Focus Gauge
# ------------------------------------------------

def render_focus_gauge(score):

    sc = score.get("score",0)

    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=sc,
        title={"text":"Focus Score"},
        gauge={
            "axis":{"range":[0,100]},
            "steps":[
                {"range":[0,40],"color":"red"},
                {"range":[40,70],"color":"yellow"},
                {"range":[70,100],"color":"green"}
            ]
        }
    ))

    st.plotly_chart(fig,use_container_width=True)


# ------------------------------------------------
# Top domains
# ------------------------------------------------

def render_top_domains():

    st.subheader("Top Blocked Domains")

    try:

        conn = sqlite3.connect(db_path())

        rows = conn.execute("""
        SELECT domain,COUNT(*) c
        FROM dns_queries
        WHERE blocked=1
        GROUP BY domain
        ORDER BY c DESC
        LIMIT 10
        """).fetchall()

        conn.close()

    except:
        st.warning("Database unavailable")
        return

    for d,c in rows:
        st.write(f"{d} — {c} attempts")


# ------------------------------------------------
# Domain tester
# ------------------------------------------------

def render_domain_tester():

    st.subheader("Domain Tester")

    dom = st.text_input("Test domain")

    if dom:

        r = api_get(f"/dns/check/{dom}")

        if r:

            if r["blocked"]:
                st.error("Blocked")

            else:
                st.success("Allowed")


# ------------------------------------------------
# Sidebar
# ------------------------------------------------

def render_sidebar():

    with st.sidebar:

        st.title("FocusGate")

        st.markdown("DNS: 127.0.0.1")
        st.markdown("API: localhost:8000")


# ------------------------------------------------
# MAIN
# ------------------------------------------------

def main():

    status = fetch_status()
    summary = fetch_summary()
    score = fetch_score()

    render_sidebar()

    render_header(status)

    render_metrics(summary,score)

    st.markdown("---")

    left,right = st.columns(2)

    with left:

        render_session_panel(status)

        st.markdown("---")

        render_focus_gauge(score)

    with right:

        render_live_log()

        st.markdown("---")

        render_dns_chart()

        st.markdown("---")

        render_top_domains()

        st.markdown("---")

        render_domain_tester()


main()
