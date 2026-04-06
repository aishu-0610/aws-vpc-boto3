"""
pages/1_Focus_Sessions.py  —  FocusGate Focus Sessions Page
Developer B owns this file.
"""

import time
import sqlite3
import os
from datetime import datetime

import httpx
import streamlit as st

API = "http://localhost:8000"

st.set_page_config(
    page_title="Focus Sessions · FocusGate",
    page_icon="🍅",
    layout="wide",
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&family=DM+Sans:wght@300;400;500;600&display=swap');
html, body, [class*="css"] { font-family: 'DM Sans', sans-serif; }

.big-timer {
    font-family: 'JetBrains Mono', monospace;
    font-size: 6rem;
    font-weight: 700;
    text-align: center;
    letter-spacing: 8px;
    padding: 0.5rem 0;
}
.session-type-card {
    background: linear-gradient(145deg, #0f0f2a, #0c1a28);
    border: 1px solid rgba(100,100,200,0.2);
    border-radius: 16px;
    padding: 1.5rem;
    margin-bottom: 1rem;
    transition: border-color 0.2s;
}
.session-type-card:hover { border-color: rgba(130,120,255,0.5); }
.session-type-card h3 { color: #e8e8f8; margin: 0.3rem 0; font-size: 1.1rem; }
.session-type-card p  { color: #6668aa; font-size: 0.88rem; margin: 0; }
.history-row {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.75rem;
    background: #090912;
    border: 1px solid #1a1a3a;
    border-radius: 8px;
    padding: 0.6rem 1rem;
    margin: 3px 0;
    display: grid;
    grid-template-columns: 80px 100px 160px 80px 60px 80px;
    gap: 8px;
    align-items: center;
}
.override-box {
    background: linear-gradient(145deg,#1a0505,#150a0a);
    border: 1px solid #7f1d1d;
    border-radius: 14px;
    padding: 1.5rem;
    text-align: center;
}
.math-box {
    background: linear-gradient(145deg,#0a1a0a,#050f1a);
    border: 1px solid #166534;
    border-radius: 14px;
    padding: 1.5rem;
    text-align: center;
}
</style>
""", unsafe_allow_html=True)


def api_get(path, params=None):
    try:
        return httpx.get(f"{API}{path}", params=params, timeout=3).json()
    except Exception:
        return None


def api_post(path, json=None, params=None):
    try:
        return httpx.post(f"{API}{path}", json=json, params=params, timeout=5).json()
    except Exception as e:
        return {"error": str(e)}


def db_path():
    return os.path.join(os.path.dirname(__file__), "../../data/focusgate.db")


@st.cache_data(ttl=2)
def get_status():
    return api_get("/status")


def fmt_time(seconds: int) -> str:
    h, r = divmod(int(seconds), 3600)
    m, s = divmod(r, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


# ── Page ───────────────────────────────────────────────────────────────

st.title("🍅 Focus Sessions")

status = get_status()
sess   = status.get("active_session") if status else None

if sess:
    # ── Active session view ────────────────────────────────────────────
    rem   = sess.get("remaining_s", 0)
    color = "#4ade80" if rem > 600 else "#facc15" if rem > 120 else "#f87171"

    st.markdown(
        f'<div class="big-timer" style="color:{color}">{fmt_time(rem)}</div>',
        unsafe_allow_html=True,
    )
    st.progress(max(0.0, min(1.0, 1 - rem / max(rem + 1, 1))))

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Type",     sess["type"].replace("_", " ").title())
    c2.metric("Override attempts", sess["override_attempts"])
    c3.metric("Session ID", sess["id"][:8] + "…")
    c4.metric("Ends at",  str(sess["ends_at"])[11:16])

    cats = ", ".join(status.get("active_categories", [])) or "none"
    st.info(f"🚫 Currently blocking: **{cats}**")

    st.markdown("---")

    # ── Override section ───────────────────────────────────────────────
    if status.get("hard_locked"):
        lr = status.get("lock_remaining", 0)
        st.markdown(f"""
        <div class="override-box">
            <div style="font-size:3rem">🔒</div>
            <div style="color:#f87171;font-size:1.3rem;font-weight:600;margin:0.5rem 0">
                Hard locked
            </div>
            <div style="color:#9a3333">
                Override impossible for {lr//60}m {lr%60:02d}s
            </div>
        </div>
        """, unsafe_allow_html=True)
    else:
        tab_std, tab_math, tab_confirm = st.tabs([
            "Standard override  (5 min wait)",
            "Math challenge  (2 min wait)",
            "Confirm override",
        ])

        # Standard
        with tab_std:
            st.markdown("Requesting an override issues a JWT token valid only after a 5-minute delay. This removes impulsive bypassing.")
            if st.button("🔓 Request standard override", use_container_width=True,
                         type="primary"):
                r = api_post("/session/override/request",
                             {"session_id": sess["id"], "solved_math": False})
                if r and r.get("allowed"):
                    st.session_state["ov_token"]   = r["token"]
                    st.session_state["ov_session"]  = sess["id"]
                    st.session_state["ov_valid_at"] = r["valid_at_iso"]
                    st.success(f"⏳ Token issued — valid at **{r['valid_at_iso']}**  ({r['delay']//60} min)")
                elif r:
                    st.error(f"🔒 {r.get('reason','Denied')}")

        # Math challenge
        with tab_math:
            st.markdown("Solve the challenge correctly to get a **2-minute** wait instead of 5.")
            if "math_ch" not in st.session_state:
                if st.button("🎲 Get a challenge", use_container_width=True):
                    ch = api_get("/session/math_challenge")
                    if ch:
                        st.session_state["math_ch"] = ch

            if "math_ch" in st.session_state:
                ch = st.session_state["math_ch"]
                st.markdown(f"""
                <div class="math-box">
                    <div style="font-size:1.5rem;color:#4ade80;font-family:'JetBrains Mono',monospace;font-weight:700">
                        {ch['question']}
                    </div>
                </div>
                """, unsafe_allow_html=True)

                ans_col, btn_col = st.columns([2, 1])
                with ans_col:
                    user_ans = st.number_input("Your answer", step=1,
                                               key="math_input", label_visibility="collapsed")
                with btn_col:
                    if st.button("Submit", use_container_width=True, type="primary"):
                        correct = (int(user_ans) == ch["answer"])
                        r = api_post("/session/override/request", {
                            "session_id":   sess["id"],
                            "solved_math":  correct,
                            "math_answer":  int(user_ans),
                        })
                        if r and r.get("allowed"):
                            st.session_state["ov_token"]    = r["token"]
                            st.session_state["ov_session"]  = sess["id"]
                            st.session_state["ov_valid_at"] = r["valid_at_iso"]
                            if correct:
                                st.success(f"✅ Correct! Reduced wait — token valid at **{r['valid_at_iso']}**")
                            else:
                                st.warning(f"❌ Wrong answer — standard 5-min wait. Valid at **{r['valid_at_iso']}**")
                            del st.session_state["math_ch"]

        # Confirm
        with tab_confirm:
            tok = st.session_state.get("ov_token")
            sid = st.session_state.get("ov_session")
            vat = st.session_state.get("ov_valid_at")

            if tok and sid == sess["id"]:
                st.info(f"Token issued — valid from **{vat}**")
                st.code(tok[:40] + "…", language="")
                if st.button("✅ Confirm override — end session now",
                             use_container_width=True, type="primary"):
                    r = api_post("/session/override/confirm",
                                 {"session_id": sid, "token": tok})
                    if r and "ok" in r:
                        for k in ("ov_token","ov_session","ov_valid_at"):
                            st.session_state.pop(k, None)
                        st.success("Session ended via override.")
                        st.cache_data.clear()
                        time.sleep(0.5)
                        st.rerun()
                    else:
                        detail = r.get("detail","Not yet valid") if r else "API error"
                        st.error(f"{detail}")
            else:
                st.caption("No pending override token. Request one first.")

    # Auto-refresh every second when active
    time.sleep(1)
    st.rerun()

else:
    # ── No active session — starter UI ────────────────────────────────
    st.markdown("### Start a focus session")

    # Mode cards
    cc1, cc2, cc3 = st.columns(3)
    with cc1:
        st.markdown("""
        <div class="session-type-card">
            <div style="font-size:2rem">🍅</div>
            <h3>Pomodoro</h3>
            <p>25 min focus + 5 min break.<br>Best for tasks with natural stopping points.</p>
        </div>
        """, unsafe_allow_html=True)
    with cc2:
        st.markdown("""
        <div class="session-type-card">
            <div style="font-size:2rem">🧠</div>
            <h3>Deep Work</h3>
            <p>90–180 min uninterrupted.<br>Best for complex problems requiring flow state.</p>
        </div>
        """, unsafe_allow_html=True)
    with cc3:
        st.markdown("""
        <div class="session-type-card">
            <div style="font-size:2rem">⚙️</div>
            <h3>Custom</h3>
            <p>Set your own duration and category mix. Full control.</p>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("---")
    with st.form("session_form"):
        fc1, fc2 = st.columns(2)
        with fc1:
            stype = st.selectbox("Session type", ["pomodoro", "deep_work", "custom"],
                format_func=lambda x: {
                    "pomodoro": "🍅 Pomodoro",
                    "deep_work": "🧠 Deep Work",
                    "custom": "⚙️ Custom",
                }[x])
            dur = st.slider("Duration (minutes)", 5, 240,
                            {"pomodoro":25,"deep_work":90,"custom":45}.get(stype,25), step=5)
        with fc2:
            cats = st.multiselect(
                "Block categories",
                ["social", "entertainment", "gaming", "news", "shopping"],
                default=["social", "entertainment", "gaming"],
            )
            hlock = st.checkbox("🔐 Hard lock mode — no override possible")

        submitted = st.form_submit_button("🚀 Start Session",
                                          use_container_width=True, type="primary")
        if submitted:
            if not cats:
                st.warning("Select at least one category.")
            else:
                r = api_post("/session/start", {
                    "type": stype,
                    "duration_minutes": dur,
                    "blocked_categories": cats,
                    "hard_lock": hlock,
                })
                if r and "session_id" in r:
                    st.success(f"✓ Session started  ·  {dur} min  ·  ID: {r['session_id'][:8]}…")
                    st.cache_data.clear()
                    time.sleep(0.4)
                    st.rerun()
                else:
                    st.error("Could not start — is the API running?")

    # ── Session history ────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### 📋 Session History")

    try:
        conn = sqlite3.connect(db_path())
        rows = conn.execute(
            "SELECT id, type, started_at, ends_at, status, override_attempts "
            "FROM sessions ORDER BY started_at DESC LIMIT 15"
        ).fetchall()
        conn.close()
    except Exception:
        rows = []

    STATUS_ICON = {"completed": "✅", "aborted": "⚠️", "active": "🟢"}

    if rows:
        st.markdown("""
        <div class="history-row" style="color:#6668aa">
            <span>Status</span><span>Type</span>
            <span>Started</span><span>Duration</span>
            <span>Overrides</span><span>ID</span>
        </div>
        """, unsafe_allow_html=True)
        for row in rows:
            sid, stype, started, ends, stat, overrides = row
            icon = STATUS_ICON.get(stat, "❓")
            try:
                dur_s = int((datetime.fromisoformat(ends) -
                             datetime.fromisoformat(started)).total_seconds())
                dur_str = fmt_time(dur_s)
            except Exception:
                dur_str = "?"
            st.markdown(f"""
            <div class="history-row">
                <span>{icon} {stat}</span>
                <span>{stype}</span>
                <span>{str(started)[5:16]}</span>
                <span>{dur_str}</span>
                <span>{overrides}</span>
                <span>{sid[:8]}…</span>
            </div>
            """, unsafe_allow_html=True)
    else:
        st.caption("No sessions recorded yet.")
