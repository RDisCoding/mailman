"""
ga4_collector.py
----------------
Fetches daily GA4 metrics (new users, active users, sessions, installs/conversions)
and appends a snapshot to metrics/ga4_daily.json.

Setup (one-time):
  1. Go to Google Cloud Console → create a service account
  2. Grant it "Viewer" on your GA4 property (Admin → Account Access Management)
  3. Download the JSON key → save as service_account.json in this directory
  4. Set GA4_PROPERTY_ID in agent_config.json or as env var

Run:
  python ga4_collector.py
"""

import os
import json
import time
from datetime import datetime, timedelta

METRICS_DIR = os.path.join(os.path.dirname(__file__), "metrics")
GA4_FILE    = os.path.join(METRICS_DIR, "ga4_daily.json")
SA_FILE     = os.path.join(os.path.dirname(__file__), "service_account.json")

# ── Config ────────────────────────────────────────────────────────────────────

def load_agent_config():
    cfg_path = os.path.join(os.path.dirname(__file__), "agent_config.json")
    if os.path.exists(cfg_path):
        with open(cfg_path, "r") as f:
            return json.load(f)
    return {}

def get_property_id():
    cfg = load_agent_config()
    pid = cfg.get("ga4_property_id") or os.environ.get("GA4_PROPERTY_ID", "")
    return pid

# ── GA4 Data Pull ─────────────────────────────────────────────────────────────

def fetch_ga4_metrics(date_str: str) -> dict:
    """
    Pulls GA4 metrics for a given date (YYYY-MM-DD).
    Returns a dict with key metrics.
    Requires google-analytics-data and a valid service_account.json.
    """
    property_id = get_property_id()
    if not property_id:
        print("[GA4] WARNING: ga4_property_id not set in agent_config.json. Skipping live pull.")
        return _mock_metrics(date_str)

    if not os.path.exists(SA_FILE):
        print(f"[GA4] WARNING: service_account.json not found at {SA_FILE}. Skipping live pull.")
        return _mock_metrics(date_str)

    try:
        from google.analytics.data_v1beta import BetaAnalyticsDataClient
        from google.analytics.data_v1beta.types import (
            DateRange, Dimension, Metric, RunReportRequest
        )
        from google.oauth2 import service_account

        credentials = service_account.Credentials.from_service_account_file(
            SA_FILE,
            scopes=["https://www.googleapis.com/auth/analytics.readonly"]
        )
        client = BetaAnalyticsDataClient(credentials=credentials)

        request = RunReportRequest(
            property=f"properties/{property_id}",
            date_ranges=[DateRange(start_date=date_str, end_date=date_str)],
            dimensions=[Dimension(name="date")],
            metrics=[
                Metric(name="newUsers"),
                Metric(name="activeUsers"),
                Metric(name="sessions"),
                Metric(name="screenPageViews"),
                Metric(name="averageSessionDuration"),
                Metric(name="bounceRate"),
            ],
        )
        response = client.run_report(request)

        metrics = {
            "date": date_str,
            "new_users": 0,
            "active_users": 0,
            "sessions": 0,
            "page_views": 0,
            "avg_session_duration_s": 0.0,
            "bounce_rate": 0.0,
            "installs": 0,  # updated separately via conversion event if configured
            "source": "ga4_live"
        }

        for row in response.rows:
            vals = [mv.value for mv in row.metric_values]
            metrics["new_users"]                = int(float(vals[0]))
            metrics["active_users"]             = int(float(vals[1]))
            metrics["sessions"]                 = int(float(vals[2]))
            metrics["page_views"]               = int(float(vals[3]))
            metrics["avg_session_duration_s"]   = round(float(vals[4]), 1)
            metrics["bounce_rate"]              = round(float(vals[5]), 4)

        # Pull install/conversion event separately
        conv_request = RunReportRequest(
            property=f"properties/{property_id}",
            date_ranges=[DateRange(start_date=date_str, end_date=date_str)],
            dimensions=[Dimension(name="eventName")],
            metrics=[Metric(name="eventCount")],
        )
        conv_response = client.run_report(conv_request)
        for row in conv_response.rows:
            event_name = row.dimension_values[0].value
            count      = int(row.metric_values[0].value)
            # Common Chrome extension install events
            if event_name in ("install", "extension_install", "first_open", "purchase"):
                metrics["installs"] += count

        print(f"[GA4] Pulled live metrics for {date_str}: {metrics}")
        return metrics

    except Exception as e:
        print(f"[GA4] Error fetching live metrics: {e}")
        return _mock_metrics(date_str)


def _mock_metrics(date_str: str) -> dict:
    """Returns zeroed-out metrics when GA4 is not yet configured."""
    return {
        "date": date_str,
        "new_users": 0,
        "active_users": 0,
        "sessions": 0,
        "page_views": 0,
        "avg_session_duration_s": 0.0,
        "bounce_rate": 0.0,
        "installs": 0,
        "source": "mock_not_configured"
    }

# ── Storage ───────────────────────────────────────────────────────────────────

def load_ga4_log() -> list:
    os.makedirs(METRICS_DIR, exist_ok=True)
    if not os.path.exists(GA4_FILE):
        return []
    with open(GA4_FILE, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except Exception:
            return []

def save_ga4_log(log: list):
    os.makedirs(METRICS_DIR, exist_ok=True)
    tmp = GA4_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2)
    if os.path.exists(GA4_FILE):
        os.remove(GA4_FILE)
    os.rename(tmp, GA4_FILE)

def append_daily_snapshot(date_str: str = None):
    """Fetch today's metrics and append to ga4_daily.json (deduped by date)."""
    if not date_str:
        # GA4 data for today is usually available with a 1-day lag
        date_str = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    log = load_ga4_log()
    existing_dates = {entry["date"] for entry in log}
    if date_str in existing_dates:
        print(f"[GA4] Snapshot for {date_str} already exists. Skipping.")
        return

    snapshot = fetch_ga4_metrics(date_str)
    snapshot["fetched_at"] = datetime.now().isoformat()
    log.append(snapshot)
    # Keep last 90 days only
    log = sorted(log, key=lambda x: x["date"])[-90:]
    save_ga4_log(log)
    print(f"[GA4] Saved snapshot for {date_str}.")

def get_last_n_days(n: int = 7) -> list:
    """Return the last n days of GA4 snapshots as a list."""
    log = load_ga4_log()
    return sorted(log, key=lambda x: x["date"])[-n:]

def compute_ga4_delta(days: int = 3) -> dict:
    """
    Compute totals and deltas over the last N days.
    Used by the strategy brain to assess performance.
    """
    recent = get_last_n_days(days)
    if not recent:
        return {
            "period_days": days,
            "total_new_users": 0,
            "total_sessions": 0,
            "total_installs": 0,
            "avg_bounce_rate": 0.0,
            "data_available": False
        }
    return {
        "period_days": days,
        "total_new_users": sum(d.get("new_users", 0) for d in recent),
        "total_sessions": sum(d.get("sessions", 0) for d in recent),
        "total_installs": sum(d.get("installs", 0) for d in recent),
        "avg_bounce_rate": round(
            sum(d.get("bounce_rate", 0) for d in recent) / len(recent), 4
        ),
        "data_available": True
    }

# ── Entry ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 50)
    print("  Cortogen GA4 Daily Collector")
    print("=" * 50)
    append_daily_snapshot()
    print("\nLast 7 days summary:")
    for entry in get_last_n_days(7):
        print(f"  {entry['date']} | new_users={entry['new_users']} | "
              f"installs={entry['installs']} | sessions={entry['sessions']}")
