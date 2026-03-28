"""
db.py  —  FocusGate SQLite Schema & Helpers
Developer A owns this file.

Run directly to initialise DB and seed blocklist:
    python backend/db.py
"""

import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "../data/focusgate.db")


def get_conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")   # concurrent reads + writes
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_db():
    conn = get_conn()
    c = conn.cursor()

    # ── Every DNS query is logged (even blocked ones) ──────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS dns_queries (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ts          DATETIME DEFAULT CURRENT_TIMESTAMP,
            domain      TEXT     NOT NULL,
            category    TEXT,
            blocked     INTEGER  DEFAULT 0,
            latency_ms  REAL,
            session_id  TEXT
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_dq_ts      ON dns_queries(ts)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_dq_blocked ON dns_queries(blocked)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_dq_domain  ON dns_queries(domain)")

    # ── Blocklist rules ────────────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS blocklist (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            domain      TEXT     NOT NULL UNIQUE,
            category    TEXT     NOT NULL,
            active      INTEGER  DEFAULT 1,
            added_at    DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_bl_active ON blocklist(active)")

    # ── Focus sessions ─────────────────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id                TEXT PRIMARY KEY,
            type              TEXT     NOT NULL,
            started_at        DATETIME DEFAULT CURRENT_TIMESTAMP,
            ends_at           DATETIME,
            status            TEXT     DEFAULT 'active',
            override_attempts INTEGER  DEFAULT 0,
            blocked_cats      TEXT
        )
    """)

    # ── Schedule rules (time-based blocking without a session) ─────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS schedules (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT    NOT NULL,
            categories  TEXT    NOT NULL,
            days        TEXT    NOT NULL,
            start_time  TEXT    NOT NULL,
            end_time    TEXT    NOT NULL,
            active      INTEGER DEFAULT 1
        )
    """)

    # ── Accountability partner sharing ─────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS accountability (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            partner     TEXT    NOT NULL,
            channel     TEXT    NOT NULL,
            contact     TEXT,
            token       TEXT    UNIQUE,
            active      INTEGER DEFAULT 1,
            created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()
    print(f"[DB] Initialised → {DB_PATH}")


# ── Query helpers ──────────────────────────────────────────────────────

def log_query(domain: str, blocked: bool, category: str = None,
              latency_ms: float = 0.0, session_id: str = None):
    try:
        conn = get_conn()
        conn.execute(
            "INSERT INTO dns_queries (domain, blocked, category, latency_ms, session_id) "
            "VALUES (?,?,?,?,?)",
            (domain, int(blocked), category, round(latency_ms, 3), session_id)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[DB] log_query error: {e}")


def get_blocked_domains() -> dict:
    """Returns {domain: category} for every active blocklist entry."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT domain, category FROM blocklist WHERE active=1"
    ).fetchall()
    conn.close()
    return {r["domain"]: r["category"] for r in rows}


# ── Seed data ──────────────────────────────────────────────────────────

SEED_DOMAINS = [
    # social
    ("youtube.com",      "social"), ("instagram.com",   "social"),
    ("twitter.com",      "social"), ("x.com",           "social"),
    ("tiktok.com",       "social"), ("facebook.com",    "social"),
    ("reddit.com",       "social"), ("snapchat.com",    "social"),
    ("linkedin.com",     "social"), ("pinterest.com",   "social"),
    ("tumblr.com",       "social"), ("discord.com",     "social"),
    # news
    ("bbc.com",          "news"),   ("cnn.com",         "news"),
    ("theguardian.com",  "news"),   ("nytimes.com",     "news"),
    ("buzzfeed.com",     "news"),   ("huffpost.com",    "news"),
    ("ndtv.com",         "news"),   ("timesofindia.com","news"),
    # entertainment
    ("netflix.com",      "entertainment"), ("primevideo.com","entertainment"),
    ("twitch.tv",        "entertainment"), ("disneyplus.com","entertainment"),
    ("hotstar.com",      "entertainment"), ("zee5.com",      "entertainment"),
    # gaming
    ("steampowered.com", "gaming"), ("epicgames.com",   "gaming"),
    ("roblox.com",       "gaming"), ("chess.com",       "gaming"),
    ("miniclip.com",     "gaming"), ("poki.com",        "gaming"),
    # shopping
    ("amazon.com",       "shopping"), ("ebay.com",      "shopping"),
    ("flipkart.com",     "shopping"), ("myntra.com",    "shopping"),
    ("meesho.com",       "shopping"), ("ajio.com",      "shopping"),
]


def seed_blocklist():
    conn = get_conn()
    conn.executemany(
        "INSERT OR IGNORE INTO blocklist (domain, category) VALUES (?,?)",
        SEED_DOMAINS
    )
    conn.commit()
    conn.close()
    print(f"[DB] Seeded {len(SEED_DOMAINS)} domains")


def seed_demo_queries():
    """
    Insert realistic-looking historical DNS queries so the analytics
    dashboard has data to visualise on first run.
    """
    import random
    from datetime import timedelta

    domains_blocked = [d for d, _ in SEED_DOMAINS]
    domains_allowed = [
        "google.com", "github.com", "stackoverflow.com", "docs.python.org",
        "pypi.org", "cloudflare.com", "fastapi.tiangolo.com", "streamlit.io",
        "api.anthropic.com", "npmjs.com", "mozilla.org", "wikipedia.org",
    ]
    categories = {d: c for d, c in SEED_DOMAINS}

    rows = []
    now  = datetime.now()
    for days_back in range(14, 0, -1):
        base = now - timedelta(days=days_back)
        # 50-150 queries per day spread across waking hours
        n_queries = random.randint(50, 150)
        for _ in range(n_queries):
            hour    = random.choices(range(8, 24), weights=[
                1,1,3,5,7,8,8,7,6,5,4,4,4,5,6,5,3,2,1,1,1,1,1,1
            ], k=1)[0]
            minute  = random.randint(0, 59)
            second  = random.randint(0, 59)
            ts      = base.replace(hour=hour, minute=minute, second=second)

            if random.random() < 0.35:   # 35 % blocked
                domain   = random.choice(domains_blocked)
                blocked  = 1
                category = categories[domain]
                lat      = round(random.uniform(0.1, 0.8), 3)
            else:
                domain   = random.choice(domains_allowed)
                blocked  = 0
                category = None
                lat      = round(random.uniform(5, 20), 3)

            rows.append((ts.isoformat(), domain, blocked, category, lat))

    conn = get_conn()
    conn.executemany(
        "INSERT INTO dns_queries (ts, domain, blocked, category, latency_ms) VALUES (?,?,?,?,?)",
        rows
    )
    conn.commit()
    conn.close()
    print(f"[DB] Seeded {len(rows)} demo query rows across 14 days")


if __name__ == "__main__":
    init_db()
    seed_blocklist()
    seed_demo_queries()
    print("[DB] Ready ✓")
