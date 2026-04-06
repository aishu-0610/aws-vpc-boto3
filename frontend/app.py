"""
app.py  —  FocusGate Streamlit Main Dashboard
Developer B owns this file.

Run:  streamlit run frontend/app.py
"""

import os
import sys
import time
import sqlite3
from datetime import datetime

import httpx
import streamlit as st

API = "http://localhost:8000"

# ── Page config ────────────────────────────────────────────────────────
st.set_page_config(
    page_title="FocusGate",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Global CSS ─────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=DM+Sans:wght@300;400;500;600&display=swap');

html, body, [class*="css"] {
    font-family: 'DM Sans', sans-serif;
}

/* ── Header card ── */
.fg-header {
    background: linear-gradient(135deg, #0a0a1a 0%, #11113a 60%, #0a1f2e 100%);
    border: 1px solid rgba(130,120,255,0.25);
    border-radius: 18px;
    padding: 2rem 2.5rem;
    margin-bottom: 1.5rem;
    position: relative;
    overflow: hidden;
}
.fg-header::before {
    content: '';
    position: absolute;
    top: -60px; right: -60px;
    width: 200px; height: 200px;
    background: radial-gradient(circle, rgba(124,111,247,0.15) 0%, transparent 70%);
    border-radius: 50%;
}
.fg-title {
    font-size: 2.4rem;
    font-weight: 600;
    background: linear-gradient(90deg, #8b7cf8 0%, #4facfe 50%, #8b7cf8 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    margin: 0 0 0.3rem 0;
}
.fg-subtitle { color: #6668aa; font-size: 0.95rem; margin: 0; }

/* ── Status badges ── */
.badge {
    display: inline-block;
    padding: 0.3rem 0.9rem;
    border-radius: 20px;
    font-size: 0.78rem;
    font-weight: 600;
    font-family: 'JetBrains Mono', monospace;
    letter-spacing: 0.5px;
    margin-right: 8px;
    margin-top: 0.8rem;
}
.badge-active  { background:#0a2e1a; color:#4ade80; border:1px solid #166534; }
.badge-idle    { background:#14142a; color:#6668aa; border:1px solid #2d2d5e; }
.badge-locked  { background:#2e0a0a; color:#f87171; border:1px solid #7f1d1d; }
.badge-info    { background:#0a1e2e; color:#60a5fa; border:1px solid #1e40af; }

/* ── Metric cards ── */
.metric-grid { display:grid; grid-template-columns:repeat(5,1fr); gap:12px; margin:1rem 0; }
.metric-card {
    background: linear-gradient(145deg, #12122a, #0f1f30);
    border: 1px solid rgba(100,100,200,0.2);
    border-radius: 14px;
    padding: 1.2rem;
    text-align: center;
}
.metric-value {
    font-family: 'JetBrains Mono', monospace;
    font-size: 2rem;
    font-weight: 700;
    line-height: 1;
    margin-bottom: 0.4rem;
}
.metric-label {
    font-size: 0.72rem;
    color: #5558aa;
    text-transform: uppercase;
    letter-spacing: 1.2px;
    font-weight: 500;
}

/* ── Timer ── */
.timer {
    font-family: 'JetBrains Mono', monospace;
    font-size: 4.5rem;
    font-weight: 700;
    text-align: center;
    letter-spacing: 6px;
    padding: 0.5rem 0;
}

/* ── Session card ── */
.session-card {
    background: linear-gradient(145deg, #0c1c2e, #0a0e20);
    border: 1px solid rgba(79,172,254,0.2);
    border-radius: 16px;
    padding: 1.5rem;
}

/* ── DNS log ── */
.dns-line {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.72rem;
    padding: 3px 8px;
    border-radius: 4px;
    margin: 2px 0;
    display: block;
}
.dns-blocked { background: rgba(239,68,68,0.08); color: #f87171; }
.dns-allowed { background: rgba(74,222,128,0.06); color: #4ade80; }

/* ── Streamlit overrides ── */
div[data-testid="stButton"] > button {
    border-radius: 10px;
    font-weight: 600;
    font-family: 'DM Sans', sans-serif;
    letter-spacing: 0.3px;
    transition: transform 0.15s;
}
div[data-testid="stButton"] > button:hover { transform: translateY(-1px); }
.stProgress > div > div { border-radius: 8px; }
</style>
""", unsafe_allow_html=True)


# ── API helpers ────────────────────────────────────────────────────────

def api_get(path: str, params: dict = None, ttl: int = 5):
    try:
        r = httpx.get(f"{API}{path}", params=params, timeout=3)
        return r.json()
    except Exception:
        return None


def api_post(path: str, json: dict = None, params: dict = None):
    try:
        r = httpx.post(f"{API}{path}", json=json, params=params, timeout=5)
        return r.json()
    except Exception as e:
        return {"error": str(e)}


@st.cache_data(ttl=5)
def fetch_status():
    return api_get("/status")


@st.cache_data(ttl=30)
def fetch_summary(days=7):
    return api_get("/analytics/summary", {"days": days}) or {}


@st.cache_data(ttl=30)
def fetch_score(days=7):
    return api_get("/analytics/focus-score", {"days": days}) or {}


# ── DB path helper ─────────────────────────────────────────────────────
def db_path():
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "../data/focusgate.db")


# ── Rendering helpers ──────────────────────────────────────────────────

def render_header(status):
    active  = status and status.get("active_session")
    locked  = status and status.get("hard_locked")
    n_block = status.get("blocked_count", 0) if status else 0

    badge_session = (
        '<span class="badge badge-locked">🔒 HARD LOCKED</span>' if locked else
        '<span class="badge badge-active">● FOCUS ACTIVE</span>' if active else
        '<span class="badge badge-idle">○ IDLE</span>'
    )
    badge_count = f'<span class="badge badge-info">🛡 {n_block:,} domains blocked</span>'

    st.markdown(f"""
    <div class="fg-header">
      <div class="fg-title">🎯 FocusGate</div>
      <div class="fg-subtitle">
        Context-aware DNS productivity filter &nbsp;·&nbsp;
        DNS-over-HTTPS &nbsp;·&nbsp; Behavioral analytics
      </div>
      {badge_session}{badge_count}
    </div>
    """, unsafe_allow_html=True)


def render_metrics(summary, score):
    total    = summary.get("total", 0)
    blocked  = summary.get("blocked", 0)
    br       = summary.get("block_rate", 0)
    sessions = summary.get("sessions", 0)
    sc       = score.get("score", 0)

    sc_color = "#4ade80" if sc >= 70 else "#facc15" if sc >= 40 else "#f87171"
    br_color = "#f87171" if br > 40 else "#facc15" if br > 20 else "#4ade80"

    st.markdown(f"""
    <div class="metric-grid">
      <div class="metric-card">
        <div class="metric-value" style="color:#60a5fa">{total:,}</div>
        <div class="metric-label">DNS Queries</div>
      </div>
      <div class="metric-card">
        <div class="metric-value" style="color:#f87171">{blocked:,}</div>
        <div class="metric-label">Blocked</div>
      </div>
      <div class="metric-card">
        <div class="metric-value" style="color:{br_color}">{br}%</div>
        <div class="metric-label">Block Rate</div>
      </div>
      <div class="metric-card">
        <div class="metric-value" style="color:{sc_color}">{sc}</div>
        <div class="metric-label">Focus Score</div>
      </div>
      <div class="metric-card">
        <div class="metric-value" style="color:#a78bfa">{sessions}</div>
        <div class="metric-label">Sessions</div>
      </div>
    </div>
    """, unsafe_allow_html=True)


def render_session_panel(status):
    st.markdown("### ⚡ Focus Session")
    sess = status.get("active_session") if status else None

    if sess:
        rem  = sess.get("remaining_s", 0)
        m, s = divmod(rem, 60)
        h, m = divmod(m, 60)

        color = "#4ade80" if rem > 600 else "#facc15" if rem > 120 else "#f87171"
        timer = f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"

        st.markdown(f'<div class="timer" style="color:{color}">{timer}</div>',
                    unsafe_allow_html=True)

        total_s = sess.get("remaining_s", 1) + 1
        prog    = max(0.0, min(1.0, 1 - rem / max(1, total_s)))
        st.progress(prog)

        c1, c2, c3 = st.columns(3)
        c1.metric("Type",     sess["type"].replace("_", " ").title())
        c2.metric("Overrides", sess["override_attempts"])
        c3.metric("Blocking",
                  ", ".join(status.get("active_categories", []))[:20] or "—")

        if status.get("hard_locked"):
            lock_rem = status.get("lock_remaining", 0)
            lm, ls   = divmod(lock_rem, 60)
            st.error(f"🔒 Hard locked — {lm}m {ls:02d}s until override possible")
        else:
            st.markdown("**Override controls**")
            col_req, col_confirm, col_end = st.columns(3)

            with col_req:
                if st.button("🔓 Request override", use_container_width=True):
                    r = api_post("/session/override/request",
                                 {"session_id": sess["id"], "solved_math": False})
                    if r and r.get("allowed"):
                        st.session_state["ov_token"]    = r["token"]
                        st.session_state["ov_valid_at"] = r["valid_at_iso"]
                        st.session_state["ov_session"]  = sess["id"]
                        st.warning(f"⏳ Token ready at **{r['valid_at_iso']}** "
                                   f"({r['delay']//60} min wait)")
                    else:
                        st.error(r.get("reason", "Denied") if r else "API error")

            with col_confirm:
                tok = st.session_state.get("ov_token")
                sid = st.session_state.get("ov_session")
                if tok and sid == sess["id"]:
                    if st.button("✅ Use token now", use_container_width=True):
                        r = api_post("/session/override/confirm",
                                     {"session_id": sid, "token": tok})
                        if r and "ok" in r:
                            for k in ("ov_token","ov_valid_at","ov_session"):
                                st.session_state.pop(k, None)
                            st.cache_data.clear()
                            st.rerun()
                        else:
                            detail = r.get("detail", "Not yet valid") if r else "API error"
                            st.error(detail)

            with col_end:
                if st.button("⏹ End session", use_container_width=True,
                             type="secondary"):
                    api_post("/session/end", params={"session_id": sess["id"]})
                    st.cache_data.clear()
                    st.rerun()

    else:
        _session_starter()


def _session_starter():
    with st.form("quick_start_form"):
        c1, c2 = st.columns(2)
        with c1:
            stype = st.selectbox("Session type", [
                "pomodoro", "deep_work", "custom"
            ], format_func=lambda x: {
                "pomodoro":  "🍅 Pomodoro (25 min)",
                "deep_work": "🧠 Deep Work (90 min)",
                "custom":    "⚙️ Custom",
            }[x])
            default_dur = {"pomodoro": 25, "deep_work": 90, "custom": 45}
            dur = st.slider("Duration (min)", 5, 240,
                            default_dur.get(stype, 25), step=5)

        with c2:
            cats = st.multiselect(
                "Block categories",
                ["social", "entertainment", "gaming", "news", "shopping"],
                default=["social", "entertainment", "gaming"],
            )
            hlock = st.checkbox("🔐 Hard lock (no override during session)")

        if st.form_submit_button("🚀 Start Focus Session",
                                  use_container_width=True, type="primary"):
            if not cats:
                st.warning("Select at least one category to block.")
            else:
                r = api_post("/session/start", {
                    "type": stype,
                    "duration_minutes": dur,
                    "blocked_categories": cats,
                    "hard_lock": hlock,
                })
                if r and "session_id" in r:
                    st.success(f"Session started ✓  ID: {r['session_id'][:8]}…")
                    st.cache_data.clear()
                    time.sleep(0.4)
                    st.rerun()
                else:
                    st.error("Could not start session — is the API running?")


def render_live_log():
    st.markdown("### 📡 Live DNS Feed")
    try:
        conn = sqlite3.connect(db_path())
        rows = conn.execute(
            "SELECT ts, domain, blocked, category "
            "FROM dns_queries ORDER BY ts DESC LIMIT 25"
        ).fetchall()
        conn.close()
    except Exception as e:
        st.caption(f"DB unavailable: {e}")
        return

    if not rows:
        st.caption("No queries yet — point your DNS to 127.0.0.1 and browse.")
        return

    html = ""
    for ts, domain, blocked, cat in rows:
        ts_str = str(ts)[11:19]
        cat_str = f"[{cat}]" if cat else ""
        icon    = "✗" if blocked else "✓"
        cls     = "dns-blocked" if blocked else "dns-allowed"
        html += (
            f'<span class="dns-line {cls}">'
            f'{icon} {ts_str}  {domain:<42} {cat_str}'
            f'</span>'
        )
    st.markdown(html, unsafe_allow_html=True)


# ── Quick domain tester ────────────────────────────────────────────────

def render_domain_tester():
    st.markdown("### 🔍 Domain Tester")
    test_domain = st.text_input("Test a domain", placeholder="youtube.com",
                                 key="test_domain_input")
    if test_domain:
        r = api_get(f"/dns/check/{test_domain.strip()}")
        if r:
            if r["blocked"]:
                st.error(f"🚫 **{test_domain}** would be BLOCKED  ·  {r['reason']}")
            else:
                st.success(f"✅ **{test_domain}** would be ALLOWED")
        else:
            st.warning("API unreachable")


# ── Sidebar ────────────────────────────────────────────────────────────

def render_sidebar(status):
    with st.sidebar:
        st.markdown("## FocusGate")
        st.markdown("---")

        if status:
            st.markdown("**System**")
            st.markdown(f"🌐 DNS: `127.0.0.1:{os.environ.get('DNS_PORT', 5353)}`")
            st.markdown(f"🔗 API: `localhost:8000`")
            st.markdown(f"📊 Dashboard: `localhost:8501`")
            st.markdown("---")
            cats = status.get("active_categories", [])
            if cats:
                st.markdown("**Blocked now**")
                for c in cats:
                    st.markdown(f"🚫 {c}")
                st.markdown("---")

        st.markdown("**Setup DNS**")
        st.code("# macOS\nsudo networksetup -setdnsservers Wi-Fi 127.0.0.1\n\n# Linux\necho 'nameserver 127.0.0.1' | sudo tee /etc/resolv.conf\n\n# Test\ndig @127.0.0.1 -p 5353 youtube.com", language="bash")

        st.markdown("---")
        st.markdown("**Pages**")
        st.markdown("1️⃣ [Focus Sessions](http://localhost:8501/Focus_Sessions)")
        st.markdown("2️⃣ [Analytics](http://localhost:8501/Analytics)")
        st.markdown("3️⃣ [Rules](http://localhost:8501/Rules)")
        st.markdown("4️⃣ [Accountability](http://localhost:8501/Accountability)")


# ── Main ───────────────────────────────────────────────────────────────

def main():
    status  = fetch_status()
    summary = fetch_summary(7)
    score   = fetch_score(7)

    if status is None:
        st.error(
            "⚠️ Cannot reach FocusGate API at localhost:8000\n\n"
            "Run:  `uvicorn backend.api:app --port 8000 --reload`"
        )

    render_sidebar(status or {})
    render_header(status or {})
    render_metrics(summary, score)

    st.markdown("---")
    left, right = st.columns([1, 1])

    with left:
        render_session_panel(status or {})

    with right:
        render_live_log()
        st.markdown("---")
        render_domain_tester()

    # Auto-refresh when session active
    if status and status.get("active_session"):
        time.sleep(1)
        st.rerun()


main()
