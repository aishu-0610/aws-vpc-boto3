"""
pages/4_Accountability.py  —  FocusGate Accountability Partner
Developer B owns this file.

Features:
  - Connect a partner via Telegram or email
  - Generate a read-only share link (token-protected)
  - Preview the weekly report
  - List connected partners
  - Remove partners
  - Full-text report viewer
"""

import sqlite3
import os

import httpx
import streamlit as st

API = "http://localhost:8000"

st.set_page_config(
    page_title="Accountability · FocusGate",
    page_icon="🤝",
    layout="wide",
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&family=DM+Sans:wght@300;400;500;600&display=swap');
html, body, [class*="css"] { font-family: 'DM Sans', sans-serif; }

.partner-card {
    background: #09091a;
    border: 1px solid #1a1a3a;
    border-radius: 12px;
    padding: 1rem 1.25rem;
    margin: 6px 0;
    display: flex;
    align-items: center;
    justify-content: space-between;
}
.partner-name  { color: #c0c0e0; font-weight: 600; font-size: 1rem; }
.partner-meta  { color: #5558aa; font-size: 0.8rem; margin-top: 2px; }
.partner-badge {
    background: #0a1e2e;
    color: #60a5fa;
    border: 1px solid #1e40af;
    border-radius: 12px;
    padding: 2px 10px;
    font-size: 0.72rem;
    font-family: 'JetBrains Mono', monospace;
}
.how-card {
    background: linear-gradient(145deg,#0a0a1e,#0c1220);
    border: 1px solid rgba(100,100,200,0.15);
    border-radius: 14px;
    padding: 1.5rem;
    text-align: center;
}
.how-icon  { font-size: 2rem; margin-bottom: 0.5rem; }
.how-title { color: #c0c0e0; font-weight: 600; margin-bottom: 0.4rem; }
.how-desc  { color: #5558aa; font-size: 0.88rem; line-height: 1.5; }
</style>
""", unsafe_allow_html=True)


def api_get(path, params=None):
    try:
        r = httpx.get(f"{API}{path}", params=params or {}, timeout=4)
        return r.json() if r.headers.get("content-type","").startswith("application/json") else r.text
    except Exception:
        return None


def api_post(path, json=None):
    try:
        return httpx.post(f"{API}{path}", json=json, timeout=5).json()
    except Exception as e:
        return {"error": str(e)}


def api_delete(path):
    try:
        return httpx.delete(f"{API}{path}", timeout=5).json()
    except Exception as e:
        return {"error": str(e)}


def db_path():
    return os.path.join(os.path.dirname(__file__), "../../data/focusgate.db")


# ── Page ───────────────────────────────────────────────────────────────

st.title("🤝 Accountability Partner")

st.markdown("""
Share your weekly distraction report with a friend or mentor.
They get **read-only visibility only** — no ability to change your rules, end sessions,
or control FocusGate in any way. This is gentle social accountability, not surveillance.
""")

# ── How it works ───────────────────────────────────────────────────────
h1, h2, h3 = st.columns(3)
with h1:
    st.markdown("""
    <div class="how-card">
        <div class="how-icon">🔗</div>
        <div class="how-title">1. Generate a share link</div>
        <div class="how-desc">
            Enter your partner's name and contact.
            FocusGate creates a unique read-only token.
        </div>
    </div>
    """, unsafe_allow_html=True)
with h2:
    st.markdown("""
    <div class="how-card">
        <div class="how-icon">📊</div>
        <div class="how-title">2. Partner views your report</div>
        <div class="how-desc">
            Weekly summary: total attempts, focus score,
            top distraction sites, peak distraction hour.
        </div>
    </div>
    """, unsafe_allow_html=True)
with h3:
    st.markdown("""
    <div class="how-card">
        <div class="how-icon">🛡️</div>
        <div class="how-title">3. You keep full control</div>
        <div class="how-desc">
            Partners cannot change settings or end sessions.
            Visibility only — respects your autonomy.
        </div>
    </div>
    """, unsafe_allow_html=True)

st.markdown("---")

# ── Main columns ───────────────────────────────────────────────────────
col_add, col_preview = st.columns([1, 1])

with col_add:
    st.subheader("🔗 Connect a partner")

    with st.form("add_partner_form"):
        p_name    = st.text_input("Partner's name", placeholder="e.g. Ravi Kumar")
        p_channel = st.selectbox("Notification channel", ["email", "telegram", "none"])
        p_contact = st.text_input(
            "Contact",
            placeholder="email@example.com  or  Telegram chat ID (numeric)",
            help="Used for future notification features. Leave blank if unsure."
        )

        if st.form_submit_button("🔗 Generate share link",
                                  use_container_width=True, type="primary"):
            if p_name.strip():
                r = api_post("/accountability/add", {
                    "partner_name": p_name.strip(),
                    "channel":      p_channel,
                    "contact":      p_contact.strip() or None,
                })
                if r and "token" in r:
                    st.success("✓ Partner added!")
                    st.markdown("**Share this link with your partner:**")
                    share_url = r.get("share_url", "")
                    st.code(share_url)
                    st.caption(
                        "Anyone with this link can view your weekly report. "
                        "Revoke access anytime by removing the partner below."
                    )
                    st.cache_data.clear()
                else:
                    st.error(f"Failed: {r}")
            else:
                st.warning("Enter a partner name.")

    st.markdown("---")

    # ── Connected partners list ────────────────────────────────────────
    st.subheader("👥 Connected partners")

    try:
        conn = sqlite3.connect(db_path())
        partners = conn.execute(
            "SELECT id, partner, channel, token, created_at "
            "FROM accountability WHERE active=1 ORDER BY created_at DESC"
        ).fetchall()
        conn.close()
    except Exception:
        partners = []

    if partners:
        for pid, pname, channel, token, created in partners:
            ch_icon = {"telegram": "📱", "email": "✉️", "none": "🔇"}.get(channel, "🔗")
            st.markdown(f"""
            <div class="partner-card">
                <div>
                    <div class="partner-name">{pname}</div>
                    <div class="partner-meta">{ch_icon} {channel}  ·  added {str(created)[:10]}</div>
                </div>
                <span class="partner-badge">{token[:12]}…</span>
            </div>
            """, unsafe_allow_html=True)

        st.markdown("---")
        st.markdown("**Remove a partner**")
        del_id = st.number_input("Partner ID to remove", min_value=1, step=1,
                                  key="del_partner_id")
        if st.button("🗑️ Remove partner", key="del_partner_btn"):
            api_delete(f"/accountability/{int(del_id)}")
            st.success(f"Partner {del_id} removed.")
            st.rerun()
    else:
        st.info("No partners connected yet.")


with col_preview:
    st.subheader("📄 Weekly report preview")
    st.caption("This is what your accountability partner sees.")

    days_report = st.select_slider("Report window", [3, 7, 14, 30], value=7,
                                   format_func=lambda d: f"Last {d} days",
                                   key="report_days")

    if st.button("🔄 Refresh report", use_container_width=True):
        st.cache_data.clear()

    @st.cache_data(ttl=60)
    def get_report(d):
        return api_get("/analytics/report", {"days": d})

    report = get_report(days_report)
    if report and isinstance(report, str):
        st.code(report, language="")
    elif report and isinstance(report, dict):
        st.code(report.get("report", "No data"), language="")
    else:
        st.info("No report data yet. Queries will appear after blocking activity.")

    st.markdown("---")
    st.subheader("🔑 View a report by token")
    token_input = st.text_input("Paste a share token / URL", placeholder="http://localhost:8000/accountability/report/...")
    if token_input:
        # Extract token from URL if pasted
        tok = token_input.split("/")[-1].strip()
        r   = api_get(f"/accountability/report/{tok}")
        if r and isinstance(r, str):
            st.code(r, language="")
        elif r and isinstance(r, dict):
            st.error(r.get("detail", "Not found"))
        else:
            st.warning("Could not fetch report.")
