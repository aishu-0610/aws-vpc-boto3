"""
pages/3_Rules.py  —  FocusGate Rules Manager
Developer B owns this file.

Features:
  - View / filter / remove blocked domains
  - Add individual domains
  - Bulk import from .txt file
  - Add / view time-based schedule rules
  - Live domain tester (would this domain be blocked right now?)
"""

import httpx
import pandas as pd
import streamlit as st

API = "http://localhost:8000"

st.set_page_config(
    page_title="Rules · FocusGate",
    page_icon="🛡️",
    layout="wide",
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&family=DM+Sans:wght@300;400;500;600&display=swap');
html, body, [class*="css"] { font-family: 'DM Sans', sans-serif; }

.schedule-card {
    background:#090912;
    border:1px solid #1a1a3a;
    border-radius:10px;
    padding:0.9rem 1.2rem;
    margin:4px 0;
    display:grid;
    grid-template-columns:200px 1fr 1fr 120px;
    gap:12px;
    align-items:center;
    font-size:0.85rem;
}
.cat-badge {
    display:inline-block;
    padding:2px 8px;
    border-radius:12px;
    font-size:0.72rem;
    font-weight:600;
    font-family:'JetBrains Mono',monospace;
    margin-right:4px;
}
</style>
""", unsafe_allow_html=True)

CAT_COLORS = {
    "social":        ("#1e1060", "#a78bfa"),
    "entertainment": ("#1a0505", "#f87171"),
    "gaming":        ("#0a1a0a", "#4ade80"),
    "news":          ("#1a1000", "#facc15"),
    "shopping":      ("#0a1a1a", "#22d3ee"),
    "custom":        ("#1a1a1a", "#9ca3af"),
}


def badge(cat: str) -> str:
    bg, fg = CAT_COLORS.get(cat, ("#111", "#999"))
    return (f'<span class="cat-badge" '
            f'style="background:{bg};color:{fg};border:1px solid {fg}40">'
            f'{cat}</span>')


def api_get(path, params=None):
    try:
        return httpx.get(f"{API}{path}", params=params or {}, timeout=4).json()
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


# ── Page ───────────────────────────────────────────────────────────────

st.title("🛡️ Rules Manager")

tab_domains, tab_schedules, tab_import, tab_test = st.tabs([
    "Blocked Domains", "Time Schedules", "Bulk Import", "Live Tester",
])


# ══ Tab 1: Domains ════════════════════════════════════════════════════

with tab_domains:
    add_col, list_col = st.columns([1, 2])

    with add_col:
        st.markdown("#### ➕ Add domain")
        with st.form("add_domain_form"):
            new_domain = st.text_input("Domain", placeholder="example.com")
            new_cat    = st.selectbox("Category",
                ["social","entertainment","gaming","news","shopping","custom"])
            if st.form_submit_button("Add to blocklist", use_container_width=True,
                                     type="primary"):
                if new_domain.strip():
                    r = api_post("/rules/domain",
                                 {"domain": new_domain.strip(), "category": new_cat})
                    if r and r.get("ok"):
                        st.success(f"✓ Added {new_domain}")
                        st.cache_data.clear()
                    else:
                        st.error(f"Failed: {r}")
                else:
                    st.warning("Enter a domain first.")

        st.markdown("---")
        st.markdown("#### 🗑️ Remove domain")
        with st.form("remove_domain_form"):
            rem_domain = st.text_input("Domain to remove")
            if st.form_submit_button("Remove", use_container_width=True):
                if rem_domain.strip():
                    api_delete(f"/rules/domain/{rem_domain.strip()}")
                    st.success(f"Removed {rem_domain}")
                    st.cache_data.clear()

    with list_col:
        st.markdown("#### 📋 Blocklist")

        @st.cache_data(ttl=15)
        def get_rules():
            return api_get("/rules") or []

        rules = get_rules()

        if rules:
            df = pd.DataFrame(rules)
            df["active"] = df["active"].map({1: True, 0: False})

            categories = sorted(df["category"].unique().tolist())
            sel_cats   = st.multiselect("Filter by category", categories,
                                        default=categories, key="cat_filter")
            filtered   = df[df["category"].isin(sel_cats)] if sel_cats else df
            active_only = st.checkbox("Active only", value=True)
            if active_only:
                filtered = filtered[filtered["active"] == True]

            st.caption(f"Showing **{len(filtered)}** of **{len(df)}** rules")

            # Render as styled table
            rows_html = ""
            for _, row in filtered.iterrows():
                cat  = row["category"] or "custom"
                dot  = "🟢" if row["active"] else "⚫"
                rows_html += (
                    f"<tr>"
                    f"<td style='padding:6px 8px;color:#c0c0e0'>{dot} {row['domain']}</td>"
                    f"<td style='padding:6px 8px'>{badge(cat)}</td>"
                    f"<td style='padding:6px 8px;color:#5558aa;font-size:0.78rem'>"
                    f"{str(row.get('added_at',''))[:10]}</td>"
                    f"</tr>"
                )
            st.markdown(f"""
            <div style="max-height:420px;overflow-y:auto;border:1px solid #1a1a3a;border-radius:10px">
            <table style="width:100%;border-collapse:collapse;font-size:0.82rem">
                <thead>
                    <tr style="background:#0a0a1a;color:#5558aa;position:sticky;top:0">
                        <th style="padding:8px 8px;text-align:left">Domain</th>
                        <th style="padding:8px 8px;text-align:left">Category</th>
                        <th style="padding:8px 8px;text-align:left">Added</th>
                    </tr>
                </thead>
                <tbody>{rows_html}</tbody>
            </table>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.info("No rules yet. Add domains above or use Bulk Import.")


# ══ Tab 2: Schedules ═════════════════════════════════════════════════

with tab_schedules:
    add_s_col, list_s_col = st.columns([1, 1])

    with add_s_col:
        st.markdown("#### ➕ Add schedule rule")
        st.caption("Automatically block categories during specific times — even without an active session.")
        with st.form("add_schedule_form"):
            s_name  = st.text_input("Rule name", placeholder="Work hours")
            s_cats  = st.multiselect("Block categories",
                ["social","entertainment","gaming","news","shopping"],
                default=["social"])
            s_days  = st.multiselect("Active days",
                ["mon","tue","wed","thu","fri","sat","sun"],
                default=["mon","tue","wed","thu","fri"])
            s_start = st.time_input("Block from")
            s_end   = st.time_input("Block until")

            if st.form_submit_button("Add schedule", use_container_width=True,
                                     type="primary"):
                if s_name and s_cats and s_days:
                    r = api_post("/rules/schedule", {
                        "name":       s_name,
                        "categories": s_cats,
                        "days":       s_days,
                        "start_time": s_start.strftime("%H:%M"),
                        "end_time":   s_end.strftime("%H:%M"),
                    })
                    if r and r.get("ok"):
                        st.success(f"✓ Schedule '{s_name}' added")
                        st.cache_data.clear()
                    else:
                        st.error("Failed to add schedule")
                else:
                    st.warning("Fill in all fields.")

    with list_s_col:
        st.markdown("#### 📅 Active schedules")

        @st.cache_data(ttl=15)
        def get_schedules():
            return api_get("/rules/schedules") or []

        schedules = get_schedules()
        if schedules:
            for s in schedules:
                active_dot = "🟢" if s.get("active") else "⚫"
                cats_html  = "".join(badge(c.strip())
                                     for c in s["categories"].split(","))
                st.markdown(f"""
                <div class="schedule-card">
                    <div style="color:#c0c0e0;font-weight:500">
                        {active_dot} {s['name']}
                    </div>
                    <div>{cats_html}</div>
                    <div style="color:#6668aa">
                        {s['days'].replace(',', ' ')}
                    </div>
                    <div style="font-family:'JetBrains Mono',monospace;color:#9090c0">
                        {s['start_time']} → {s['end_time']}
                    </div>
                </div>
                """, unsafe_allow_html=True)

            st.markdown("---")
            del_id = st.number_input("Delete schedule ID", min_value=1, step=1)
            if st.button("🗑️ Delete schedule", key="del_sched"):
                api_delete(f"/rules/schedule/{int(del_id)}")
                st.success(f"Deleted schedule {del_id}")
                st.cache_data.clear()
                st.rerun()
        else:
            st.info("No schedules yet. Add one to auto-block during work hours.")


# ══ Tab 3: Bulk Import ════════════════════════════════════════════════

with tab_import:
    st.markdown("#### 📥 Import from .txt file")
    st.markdown("One domain per line. All imported domains get the category you choose.")

    uploaded = st.file_uploader("Upload blocklist .txt", type=["txt"])
    imp_cat  = st.selectbox("Assign category",
        ["social","entertainment","gaming","news","shopping","custom"])

    if uploaded:
        raw     = uploaded.read().decode("utf-8", errors="ignore")
        domains = [
            line.strip().lstrip("#").strip()
            for line in raw.splitlines()
            if line.strip() and not line.strip().startswith("#")
            and " " not in line.strip()   # skip hosts-file lines with IPs
        ]
        # Strip leading 0.0.0.0 / 127.0.0.1 (standard hosts-file format)
        domains = [d.split()[-1] if d.startswith(("0.0.0.0","127.0.0.1")) else d
                   for d in domains]
        domains = [d for d in domains if "." in d and len(d) > 3]

        st.info(f"Found **{len(domains)}** domains to import")
        with st.expander("Preview first 20"):
            st.code("\n".join(domains[:20]))

        if st.button("📥 Import all", type="primary", use_container_width=True):
            prog = st.progress(0.0)
            ok   = 0
            for i, d in enumerate(domains):
                r = api_post("/rules/domain", {"domain": d, "category": imp_cat})
                if r and r.get("ok"):
                    ok += 1
                prog.progress((i + 1) / len(domains))
            st.success(f"✓ Imported {ok}/{len(domains)} domains as **{imp_cat}**")
            st.cache_data.clear()

    st.markdown("---")
    st.markdown("""
**Popular free blocklists:**
| Source | URL |
|---|---|
| StevenBlack (ads+malware) | https://github.com/StevenBlack/hosts |
| The Block List Project | https://github.com/blocklistproject/Lists |
| EasyList | https://easylist.to |
| OISD | https://oisd.nl |
""")


# ══ Tab 4: Live Tester ════════════════════════════════════════════════

with tab_test:
    st.markdown("#### 🔍 Live domain tester")
    st.caption("Check whether a domain would be blocked by FocusGate **right now** "
               "(respects active session + schedule rules).")

    test_input = st.text_area(
        "Domains to test (one per line)",
        placeholder="youtube.com\nreddit.com\ngoogle.com",
        height=140,
    )

    if st.button("🔍 Test all", type="primary", use_container_width=True):
        domains_to_test = [
            d.strip() for d in test_input.splitlines()
            if d.strip()
        ]
        if not domains_to_test:
            st.warning("Enter at least one domain.")
        else:
            results = []
            for d in domains_to_test:
                r = api_get(f"/dns/check/{d}")
                if r:
                    results.append(r)

            for r in results:
                if r["blocked"]:
                    st.error(f"🚫 **{r['domain']}**  →  BLOCKED  ·  category: {r.get('category','?')}")
                else:
                    st.success(f"✅ **{r['domain']}**  →  ALLOWED")
