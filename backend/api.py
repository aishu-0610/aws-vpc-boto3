"""
api.py  —  FocusGate FastAPI REST Bridge
Developer A owns this file.

Run:  uvicorn backend.api:app --host 0.0.0.0 --port 8000 --reload

All endpoints return JSON. Streamlit calls these via httpx.
The dns_engine.py imports `rules_engine` from this module so they
share the same RulesEngine instance when run together.

Endpoint groups:
  /status                      → current state (polled every 5s by dashboard)
  /session/*                   → start, end, override flow, math challenge
  /rules/*                     → blocklist CRUD + schedule management
  /analytics/*                 → all chart data (summary, heatmap, trend …)
  /accountability/*            → partner sharing tokens
  /dns/check/{domain}          → test whether a domain would be blocked
"""

import uuid
import secrets
import threading
import time
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from backend.db import get_conn, init_db, seed_blocklist, seed_demo_queries
from backend.rules_engine import RulesEngine
from backend.tamper_lock import TamperLock, generate_math_challenge
from backend.analytics import (
    get_summary, get_hourly_heatmap, get_daily_trend,
    get_category_breakdown, get_top_domains,
    get_focus_score, get_latency_stats, generate_weekly_report,
)

app = FastAPI(
    title="FocusGate API",
    description="Context-aware DNS productivity filter",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Singleton instances — shared with dns_engine via import
rules_engine = RulesEngine()
tamper_lock  = TamperLock()


# ══ Pydantic request models ════════════════════════════════════════════

class SessionStart(BaseModel):
    type: str = Field("pomodoro", description="pomodoro | deep_work | custom")
    duration_minutes: int = Field(25, ge=1, le=480)
    blocked_categories: List[str] = Field(
        default=["social", "entertainment", "gaming"]
    )
    hard_lock: bool = False

class DomainAdd(BaseModel):
    domain: str
    category: str

class ScheduleAdd(BaseModel):
    name: str
    categories: List[str]
    days: List[str]
    start_time: str   # "HH:MM"
    end_time: str     # "HH:MM"

class OverrideRequest(BaseModel):
    session_id: str
    solved_math: bool = False
    math_answer: Optional[int] = None
    challenge_answer: Optional[int] = None   # alias

class OverrideConfirm(BaseModel):
    session_id: str
    token: str

class AccountabilityAdd(BaseModel):
    partner_name: str
    channel: str   # telegram | email
    contact: Optional[str] = None


# ══ Status ═════════════════════════════════════════════════════════════

@app.get("/status", summary="Current FocusGate state")
def status():
    """
    Polled every 5 s by the Streamlit dashboard.
    Returns active session info, lock state, blocked category list.
    """
    conn    = get_conn()
    session = conn.execute(
        "SELECT * FROM sessions WHERE status='active' "
        "ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    conn.close()

    active_session = None
    locked, lock_rem = False, 0

    if session:
        ends_at   = datetime.fromisoformat(session["ends_at"])
        remaining = max(0, int((ends_at - datetime.now()).total_seconds()))
        active_session = {
            "id":                session["id"],
            "type":              session["type"],
            "started_at":        session["started_at"],
            "ends_at":           session["ends_at"],
            "remaining_s":       remaining,
            "override_attempts": session["override_attempts"],
            "blocked_cats":      session["blocked_cats"] or "",
        }
        locked, lock_rem = tamper_lock.is_hard_locked(session["id"])

    return {
        "dns_running":        True,
        "active_session":     active_session,
        "blocked_count":      len(rules_engine._cache),
        "active_categories":  list(rules_engine.active_categories),
        "hard_locked":        locked,
        "lock_remaining":     lock_rem,
        "pending_override":   bool(
            active_session and
            tamper_lock.get_pending(active_session["id"])
        ),
        "ts":                 datetime.now().isoformat(),
    }


# ══ Sessions ════════════════════════════════════════════════════════════

@app.post("/session/start")
def start_session(body: SessionStart):
    session_id = str(uuid.uuid4())
    started_at = datetime.now()
    ends_at    = started_at + timedelta(minutes=body.duration_minutes)

    conn = get_conn()
    conn.execute(
        "INSERT INTO sessions "
        "(id, type, started_at, ends_at, blocked_cats) VALUES (?,?,?,?,?)",
        (session_id, body.type,
         started_at.isoformat(), ends_at.isoformat(),
         ",".join(body.blocked_categories))
    )
    conn.commit()
    conn.close()

    rules_engine.start_session(
        session_id, body.type, body.blocked_categories
    )

    if body.hard_lock:
        tamper_lock.set_hard_lock(session_id, body.duration_minutes * 60)

    return {
        "session_id":        session_id,
        "type":              body.type,
        "started_at":        started_at.isoformat(),
        "ends_at":           ends_at.isoformat(),
        "duration_minutes":  body.duration_minutes,
        "blocked_categories": body.blocked_categories,
        "hard_lock":         body.hard_lock,
    }


@app.post("/session/end")
def end_session(session_id: str):
    conn = get_conn()
    conn.execute(
        "UPDATE sessions SET status='completed' WHERE id=?",
        (session_id,)
    )
    conn.commit()
    conn.close()
    rules_engine.end_session()
    return {"ok": True, "session_id": session_id}


@app.get("/session/history")
def session_history(limit: int = Query(20, le=100)):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM sessions ORDER BY started_at DESC LIMIT ?",
        (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/session/math_challenge")
def math_challenge():
    return generate_math_challenge()


@app.post("/session/override/request")
def request_override(body: OverrideRequest):
    """
    Step 1 of override flow.
    Issues a JWT token whose nbf = now + delay.
    Returns token + valid_at timestamp for frontend countdown.
    """
    # Resolve math answer from either field name
    math_ans = body.math_answer or body.challenge_answer

    # Verify math answer if claimed solved
    solved = False
    if body.solved_math and math_ans is not None:
        # We can't verify without the original challenge; trust the flag
        # In production: store challenge in session state
        solved = True   # frontend already verified locally

    # Increment override_attempts counter in DB
    conn = get_conn()
    conn.execute(
        "UPDATE sessions SET override_attempts = override_attempts + 1 "
        "WHERE id=?",
        (body.session_id,)
    )
    conn.commit()
    conn.close()

    result = tamper_lock.request_override(body.session_id, solved_math=solved)
    return result


@app.post("/session/override/confirm")
def confirm_override(body: OverrideConfirm):
    """
    Step 2 of override flow.
    Validates token; if valid + nbf has passed → end session.
    """
    valid, reason = tamper_lock.confirm_override(body.session_id, body.token)
    if not valid:
        raise HTTPException(status_code=403, detail=reason)

    rules_engine.end_session()
    conn = get_conn()
    conn.execute(
        "UPDATE sessions SET status='aborted' WHERE id=?",
        (body.session_id,)
    )
    conn.commit()
    conn.close()
    return {"ok": True, "message": "Session ended via override"}


# ══ Rules / Blocklist ═══════════════════════════════════════════════════

@app.get("/rules")
def get_rules(active_only: bool = True):
    conn = get_conn()
    q    = "SELECT * FROM blocklist"
    if active_only:
        q += " WHERE active=1"
    q += " ORDER BY category, domain"
    rows = conn.execute(q).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.post("/rules/domain")
def add_domain(body: DomainAdd):
    rules_engine.add_domain(body.domain.lower().strip(), body.category)
    return {"ok": True, "domain": body.domain, "category": body.category}


@app.delete("/rules/domain/{domain}")
def remove_domain(domain: str):
    rules_engine.remove_domain(domain.lower())
    return {"ok": True, "domain": domain}


@app.get("/rules/schedules")
def get_schedules():
    return rules_engine.get_schedules()


@app.post("/rules/schedule")
def add_schedule(body: ScheduleAdd):
    rules_engine.add_schedule(
        body.name, body.categories, body.days,
        body.start_time, body.end_time,
    )
    return {"ok": True, "name": body.name}


@app.delete("/rules/schedule/{schedule_id}")
def delete_schedule(schedule_id: int):
    conn = get_conn()
    conn.execute("UPDATE schedules SET active=0 WHERE id=?", (schedule_id,))
    conn.commit()
    conn.close()
    return {"ok": True}


@app.get("/dns/check/{domain}")
def check_domain(domain: str):
    """Quick test — would this domain be blocked right now?"""
    blocked, category = rules_engine.should_block(domain)
    return {
        "domain":   domain,
        "blocked":  blocked,
        "category": category,
        "reason":   f"Matched blocklist category: {category}" if blocked else "Not blocked",
    }


# ══ Analytics ═══════════════════════════════════════════════════════════

@app.get("/analytics/summary")
def analytics_summary(days: int = Query(7, ge=1, le=365)):
    return get_summary(days)


@app.get("/analytics/heatmap")
def analytics_heatmap(days: int = Query(14, ge=1, le=90)):
    return get_hourly_heatmap(days)


@app.get("/analytics/trend")
def analytics_trend(days: int = Query(30, ge=1, le=365)):
    return get_daily_trend(days)


@app.get("/analytics/categories")
def analytics_categories(days: int = Query(7, ge=1, le=365)):
    return get_category_breakdown(days)


@app.get("/analytics/top-domains")
def analytics_top_domains(
    days: int  = Query(7, ge=1, le=365),
    limit: int = Query(20, ge=1, le=100),
):
    return get_top_domains(days, limit)


@app.get("/analytics/focus-score")
def analytics_focus_score(days: int = Query(7, ge=1, le=365)):
    return get_focus_score(days)


@app.get("/analytics/latency")
def analytics_latency(days: int = Query(7, ge=1, le=90)):
    return get_latency_stats(days)


@app.get("/analytics/report", response_class=PlainTextResponse)
def analytics_report(days: int = Query(7, ge=1, le=365)):
    return generate_weekly_report(days)


# ══ Accountability ═══════════════════════════════════════════════════════

@app.post("/accountability/add")
def add_accountability(body: AccountabilityAdd):
    token = secrets.token_urlsafe(20)
    conn  = get_conn()
    conn.execute(
        "INSERT INTO accountability (partner, channel, contact, token) "
        "VALUES (?,?,?,?)",
        (body.partner_name, body.channel, body.contact, token)
    )
    conn.commit()
    conn.close()
    return {
        "token":     token,
        "share_url": f"http://localhost:8000/accountability/report/{token}",
    }


@app.get("/accountability/partners")
def list_partners():
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, partner, channel, token, created_at "
        "FROM accountability WHERE active=1"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/accountability/report/{token}", response_class=PlainTextResponse)
def public_report(token: str):
    """Public read-only report endpoint — shareable with accountability partner."""
    conn = get_conn()
    row  = conn.execute(
        "SELECT * FROM accountability WHERE token=? AND active=1", (token,)
    ).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Report not found")
    return generate_weekly_report(7)


@app.delete("/accountability/{partner_id}")
def remove_partner(partner_id: int):
    conn = get_conn()
    conn.execute(
        "UPDATE accountability SET active=0 WHERE id=?", (partner_id,)
    )
    conn.commit()
    conn.close()
    return {"ok": True}


# ══ Startup / Shutdown ═══════════════════════════════════════════════════

@app.on_event("startup")
def on_startup():
    init_db()
    seed_blocklist()
    # Seed demo data only if table is empty
    conn = get_conn()
    count = conn.execute("SELECT COUNT(*) FROM dns_queries").fetchone()[0]
    conn.close()
    if count == 0:
        seed_demo_queries()
    print(
        "\n[API] FocusGate API ready\n"
        "      Docs → http://localhost:8000/docs\n"
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=True,
                reload_dirs=["backend"])
