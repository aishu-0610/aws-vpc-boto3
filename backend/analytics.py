"""
analytics.py  —  FocusGate Behavioral Analytics Engine
Developer A owns this file.

All public functions:
  get_summary(days)          → header metric cards
  get_hourly_heatmap(days)   → hour × weekday blocked-attempt matrix
  get_daily_trend(days)      → date-level total vs blocked line chart
  get_category_breakdown(days) → pie/bar chart data
  get_top_domains(days, n)   → ranked distraction site table
  get_focus_score(days)      → 0-100 score + week-over-week trend
  get_latency_stats(days)    → p50/p95/p99 latency for perf monitoring
  generate_weekly_report(days) → human-readable text report

All functions return JSON-serialisable Python dicts/lists.
They read directly from SQLite via Pandas read_sql_query.
"""

import sqlite3
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd

from db import DB_PATH

WEEKDAY_ORDER = [
    "Monday", "Tuesday", "Wednesday", "Thursday",
    "Friday", "Saturday", "Sunday",
]


def _load(days: int = 30) -> pd.DataFrame:
    """Load dns_queries for the last N days into a DataFrame."""
    since = (datetime.now() - timedelta(days=days)).isoformat()
    try:
        conn = sqlite3.connect(DB_PATH)
        df   = pd.read_sql_query(
            "SELECT id, ts, domain, blocked, category, latency_ms, session_id "
            "FROM dns_queries WHERE ts >= ? ORDER BY ts",
            conn,
            params=(since,),
            parse_dates=["ts"],
        )
        conn.close()
    except Exception:
        return pd.DataFrame(columns=[
            "id","ts","domain","blocked","category","latency_ms","session_id"
        ])

    if df.empty:
        return df

    df["hour"]    = df["ts"].dt.hour
    df["date"]    = df["ts"].dt.date
    df["weekday"] = df["ts"].dt.day_name()
    df["blocked"] = df["blocked"].fillna(0).astype(int)
    return df


# ── Public API ─────────────────────────────────────────────────────────

def get_summary(days: int = 7) -> dict:
    df = _load(days)
    if df.empty:
        return {
            "total": 0, "blocked": 0, "allowed": 0,
            "block_rate": 0.0, "sessions": 0,
            "unique_domains": 0, "top_blocked": [],
        }

    total     = len(df)
    blocked   = int(df["blocked"].sum())
    allowed   = total - blocked
    sessions  = int(df["session_id"].nunique())
    unique_d  = int(df["domain"].nunique())

    top_blocked = (
        df[df["blocked"] == 1]["domain"]
        .value_counts()
        .head(5)
        .reset_index()
        .rename(columns={"index": "domain", "domain": "attempts"})
        .to_dict("records")
    )

    return {
        "total":          total,
        "blocked":        blocked,
        "allowed":        allowed,
        "block_rate":     round(blocked / total * 100, 1) if total else 0.0,
        "sessions":       sessions,
        "unique_domains": unique_d,
        "top_blocked":    top_blocked,
    }


def get_hourly_heatmap(days: int = 14) -> list:
    """
    Returns list of {weekday, hour, attempts} for a Plotly density heatmap.
    Covers all 7 weekdays × 24 hours (missing cells filled with 0).
    """
    df = _load(days)
    blocked = df[df["blocked"] == 1] if not df.empty else df

    # Build full grid
    grid = pd.MultiIndex.from_product(
        [WEEKDAY_ORDER, range(24)],
        names=["weekday", "hour"],
    ).to_frame(index=False)

    if blocked.empty:
        grid["attempts"] = 0
        return grid.to_dict("records")

    heat = (
        blocked.groupby(["weekday", "hour"])
        .size()
        .reset_index(name="attempts")
    )
    result = grid.merge(heat, on=["weekday", "hour"], how="left").fillna(0)
    result["attempts"] = result["attempts"].astype(int)
    return result.to_dict("records")


def get_daily_trend(days: int = 30) -> list:
    """Returns list of {date, total, blocked, allowed} for a line chart."""
    df = _load(days)
    if df.empty:
        return []

    trend = (
        df.groupby("date")
        .agg(total=("id", "count"), blocked=("blocked", "sum"))
        .reset_index()
    )
    trend["allowed"]  = trend["total"] - trend["blocked"]
    trend["date"]     = trend["date"].astype(str)
    trend["blocked"]  = trend["blocked"].astype(int)
    trend["allowed"]  = trend["allowed"].astype(int)
    return trend.to_dict("records")


def get_category_breakdown(days: int = 7) -> list:
    """Returns [{category, attempts}] sorted descending."""
    df = _load(days)
    if df.empty:
        return []

    cats = (
        df[df["blocked"] == 1]
        .groupby("category")
        .size()
        .reset_index(name="attempts")
        .sort_values("attempts", ascending=False)
    )
    cats["category"] = cats["category"].fillna("unknown")
    return cats.to_dict("records")


def get_top_domains(days: int = 7, limit: int = 20) -> list:
    """Returns [{domain, attempts, category}] for top distraction sites."""
    df = _load(days)
    if df.empty:
        return []

    top = (
        df[df["blocked"] == 1]
        .groupby(["domain", "category"])
        .size()
        .reset_index(name="attempts")
        .sort_values("attempts", ascending=False)
        .head(limit)
    )
    return top.to_dict("records")


def get_focus_score(days: int = 7) -> dict:
    """
    FocusScore: 0–100.
      score = 100 × (1 − block_rate)
    Week-over-week trend compares first half vs second half of the window.
    """
    df = _load(days)
    if df.empty:
        return {
            "score": 100, "trend": "neutral",
            "blocked": 0, "total": 0,
            "details": "No data yet — start blocking!",
        }

    total   = len(df)
    blocked = int(df["blocked"].sum())
    rate    = blocked / total if total else 0
    score   = max(0, round(100 * (1 - rate)))

    # Trend: compare first vs second half
    midpoint = df["ts"].min() + (df["ts"].max() - df["ts"].min()) / 2
    old_rate = df[df["ts"] <= midpoint]["blocked"].mean()
    new_rate = df[df["ts"] >  midpoint]["blocked"].mean()

    if new_rate < old_rate - 0.02:
        trend = "improving"
    elif new_rate > old_rate + 0.02:
        trend = "worsening"
    else:
        trend = "stable"

    return {
        "score":   score,
        "trend":   trend,
        "blocked": blocked,
        "total":   total,
        "details": f"{blocked:,} distraction attempts out of {total:,} total queries",
    }


def get_latency_stats(days: int = 7) -> dict:
    """p50/p95/p99 latency — useful for performance section in interviews."""
    df = _load(days)
    if df.empty or "latency_ms" not in df.columns:
        return {"p50": 0, "p95": 0, "p99": 0, "mean": 0}

    lat = df["latency_ms"].dropna()
    if lat.empty:
        return {"p50": 0, "p95": 0, "p99": 0, "mean": 0}

    blocked_lat  = df[df["blocked"] == 1]["latency_ms"].dropna()
    allowed_lat  = df[df["blocked"] == 0]["latency_ms"].dropna()

    def stats(s: pd.Series) -> dict:
        if s.empty:
            return {"p50": 0, "p95": 0, "p99": 0, "mean": 0}
        return {
            "p50":  round(s.quantile(0.50), 2),
            "p95":  round(s.quantile(0.95), 2),
            "p99":  round(s.quantile(0.99), 2),
            "mean": round(s.mean(), 2),
        }

    return {
        "overall": stats(lat),
        "blocked": stats(blocked_lat),
        "allowed": stats(allowed_lat),
    }


def generate_weekly_report(days: int = 7) -> str:
    """Human-readable report for accountability partner sharing."""
    summary  = get_summary(days)
    score    = get_focus_score(days)
    top      = get_top_domains(days, 5)
    heatmap  = get_hourly_heatmap(days)

    # Find peak hour
    if heatmap:
        peak = max(heatmap, key=lambda x: x["attempts"])
        peak_str = f"{peak['hour']:02d}:00 on {peak['weekday']}s"
    else:
        peak_str = "N/A"

    trend_arrow = {"improving": "↑", "worsening": "↓", "stable": "→"}[
        score.get("trend", "stable")
    ]

    lines = [
        "━" * 44,
        "  📊  FocusGate Weekly Distraction Report",
        "━" * 44,
        f"  Focus Score   :  {score['score']}/100  {trend_arrow} {score['trend']}",
        f"  Total queries :  {summary['total']:,}",
        f"  Blocked       :  {summary['blocked']:,}  ({summary['block_rate']}%)",
        f"  Sessions      :  {summary['sessions']}",
        f"  Peak hour     :  {peak_str}",
        "",
        "  🔥  Top Distraction Sites",
        "  " + "─" * 40,
    ]
    for i, d in enumerate(top, 1):
        domain   = d.get("domain", "?")
        attempts = d.get("attempts", 0)
        lines.append(f"  {i}.  {domain:<30} {attempts:>4} attempts")

    lines += ["", "━" * 44]
    return "\n".join(lines)
