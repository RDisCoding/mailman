"""
metrics_logger.py
-----------------
Centralized module for reading and writing campaign metrics.
All campaign results (sent, opens, etc.) are logged here so the
strategy brain has a clean data source to reason over.

Schema for campaign_log.json entries:
{
    "campaign_id":        str   — unique id e.g. "india_dev_2026_07_14_am"
    "started_at":         ISO   — when the batch started
    "finished_at":        ISO   — when the batch finished
    "csv_file":           str   — which lead file was used
    "region":             str   — e.g. "India", "USA", "EU"
    "lead_source":        str   — e.g. "GitHub Bangalore", "Corporate AI"
    "template_used":      str   — "sales", "premium", "direct"
    "total_sent":         int
    "total_failed":       int
    "total_opens":        int   — updated async as opens come in
    "open_rate":          float — total_opens / total_sent
    "ga4_new_users_delta":int   — installs/users attributed to this window
    "ga4_installs_delta": int
    "notes":              str   — any manual notes
}
"""

import os
import json
import uuid
import time
from datetime import datetime

METRICS_DIR   = os.path.join(os.path.dirname(__file__), "metrics")
CAMPAIGN_FILE = os.path.join(METRICS_DIR, "campaign_log.json")

# ── Load / Save ───────────────────────────────────────────────────────────────

def load_campaign_log() -> list:
    os.makedirs(METRICS_DIR, exist_ok=True)
    if not os.path.exists(CAMPAIGN_FILE):
        return []
    with open(CAMPAIGN_FILE, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except Exception:
            return []

def save_campaign_log(log: list):
    os.makedirs(METRICS_DIR, exist_ok=True)
    tmp = CAMPAIGN_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2, default=str)
    if os.path.exists(CAMPAIGN_FILE):
        os.remove(CAMPAIGN_FILE)
    os.rename(tmp, CAMPAIGN_FILE)

# ── Campaign Lifecycle ────────────────────────────────────────────────────────

def start_campaign(csv_file: str, region: str, lead_source: str,
                   template: str, daily_limit: int) -> str:
    """
    Call at the beginning of a campaign batch.
    Returns the campaign_id to use for subsequent updates.
    """
    now = datetime.now()
    campaign_id = f"{region.lower().replace(' ', '_')}_{now.strftime('%Y_%m_%d_%H%M')}"

    entry = {
        "campaign_id":          campaign_id,
        "started_at":           now.isoformat(),
        "finished_at":          None,
        "csv_file":             os.path.basename(csv_file),
        "region":               region,
        "lead_source":          lead_source,
        "template_used":        template,
        "daily_limit":          daily_limit,
        "total_sent":           0,
        "total_failed":         0,
        "total_opens":          0,
        "open_events":          [],
        "open_rate":            0.0,
        "ga4_new_users_delta":  0,
        "ga4_installs_delta":   0,
        "notes":                ""
    }

    log = load_campaign_log()
    log.append(entry)
    save_campaign_log(log)
    print(f"[Metrics] Campaign started: {campaign_id}")
    return campaign_id

def finish_campaign(campaign_id: str, total_sent: int, total_failed: int,
                    notes: str = ""):
    """Call when a campaign batch finishes sending."""
    log = load_campaign_log()
    for entry in log:
        if entry["campaign_id"] == campaign_id:
            entry["finished_at"]  = datetime.now().isoformat()
            entry["total_sent"]   = total_sent
            entry["total_failed"] = total_failed
            entry["notes"]        = notes
            # Recalculate open rate in case opens were already logged
            opens = entry.get("total_opens", 0)
            entry["open_rate"] = round(opens / total_sent, 4) if total_sent > 0 else 0.0
            break
    save_campaign_log(log)
    print(f"[Metrics] Campaign finished: {campaign_id} | sent={total_sent} failed={total_failed}")

def record_sent(campaign_id: str, count: int = 1):
    """Increment the sent counter for a campaign as emails are delivered."""
    log = load_campaign_log()
    for entry in log:
        if entry["campaign_id"] == campaign_id:
            entry["total_sent"] = entry.get("total_sent", 0) + count
            sent = entry["total_sent"]
            opens = entry.get("total_opens", 0)
            entry["open_rate"] = round(opens / sent, 4) if sent > 0 else 0.0
            save_campaign_log(log)
            print(f"[Metrics] Sent tracked for campaign={campaign_id} | sent={entry['total_sent']} | rate={entry['open_rate']:.1%}")
            return
    print(f"[Metrics] Sent tracked for campaign={campaign_id} but campaign not found.")

def record_open(email: str):
    """
    Called by the tracking pixel endpoint on api.cortogen.com.
    Increments open count on the most recent campaign that sent to this email.
    This is called from server.py when a GET to /api/track/open arrives.
    """
    log = load_campaign_log()
    # Find the most recent completed or ongoing campaign and increment
    # (Simple approach: increment the last campaign entry that has sent > 0)
    for entry in reversed(log):
        if entry.get("total_sent", 0) > 0:
            opened_at = datetime.now().isoformat(timespec="seconds")
            entry["total_opens"] = entry.get("total_opens", 0) + 1
            entry.setdefault("open_events", []).append({
                "email": email,
                "opened_at": opened_at,
                "campaign_id": entry.get("campaign_id", "")
            })
            sent = entry["total_sent"]
            entry["open_rate"] = round(entry["total_opens"] / sent, 4) if sent > 0 else 0.0
            save_campaign_log(log)
            print(f"[Metrics] Open tracked for email={email} | campaign={entry['campaign_id']} | "
                  f"opens={entry['total_opens']} | rate={entry['open_rate']:.1%}")
            return
    print(f"[Metrics] Open tracked for email={email} but no active campaign found.")

def update_ga4_delta(campaign_id: str, new_users: int, installs: int):
    """Attach GA4 numbers to a specific campaign (called by strategy brain)."""
    log = load_campaign_log()
    for entry in log:
        if entry["campaign_id"] == campaign_id:
            entry["ga4_new_users_delta"] = new_users
            entry["ga4_installs_delta"]  = installs
            break
    save_campaign_log(log)

# ── Query Helpers ─────────────────────────────────────────────────────────────

def get_last_n_campaigns(n: int = 5) -> list:
    """Return the last N finished campaigns."""
    log = load_campaign_log()
    finished = [e for e in log if e.get("finished_at")]
    return finished[-n:]

def get_campaigns_since(days_ago: int = 3) -> list:
    """Return all campaigns started in the last N days."""
    from datetime import timedelta
    cutoff = (datetime.now() - timedelta(days=days_ago)).isoformat()
    log = load_campaign_log()
    return [e for e in log if e.get("started_at", "") >= cutoff]

def summarize_performance(days: int = 3) -> dict:
    """
    Aggregate performance across recent campaigns.
    Used as input context for the LLM strategy brain.
    """
    campaigns = get_campaigns_since(days)
    if not campaigns:
        return {
            "period_days": days,
            "campaigns_run": 0,
            "total_sent": 0,
            "total_opens": 0,
            "unique_opens": 0,
            "avg_open_rate": 0.0,
            "best_template": None,
            "best_region": None,
            "worst_region": None,
            "regions_tried": [],
            "templates_tried": [],
            "recent_opens": [],
            "data_available": False
        }

    total_sent  = sum(c.get("total_sent", 0) for c in campaigns)
    total_opens = sum(c.get("total_opens", 0) for c in campaigns)
    avg_open    = round(total_opens / total_sent, 4) if total_sent > 0 else 0.0

    recent_opens = []
    for campaign in campaigns:
        for event in campaign.get("open_events", []):
            recent_opens.append({
                "email": event.get("email", ""),
                "opened_at": event.get("opened_at", ""),
                "campaign_id": event.get("campaign_id", campaign.get("campaign_id", "")),
                "region": campaign.get("region", "Unknown"),
                "template": campaign.get("template_used", "Unknown")
            })
    recent_opens.sort(key=lambda x: x.get("opened_at", ""), reverse=True)
    unique_opens = len({event.get("email", "") for event in recent_opens if event.get("email")})

    # Best/worst by open rate
    finished = [c for c in campaigns if c.get("total_sent", 0) > 5]
    best  = max(finished, key=lambda x: x.get("open_rate", 0), default=None)
    worst = min(finished, key=lambda x: x.get("open_rate", 0), default=None)

    regions   = list({c.get("region", "Unknown") for c in campaigns})
    templates = list({c.get("template_used", "Unknown") for c in campaigns})

    # Best template
    template_rates = {}
    for c in finished:
        t = c.get("template_used", "unknown")
        template_rates.setdefault(t, []).append(c.get("open_rate", 0))
    best_tmpl = max(template_rates, key=lambda t: sum(template_rates[t])/len(template_rates[t]),
                    default=None) if template_rates else None

    return {
        "period_days":      days,
        "campaigns_run":    len(campaigns),
        "total_sent":       total_sent,
        "total_opens":      total_opens,
        "unique_opens":     unique_opens,
        "avg_open_rate":    avg_open,
        "best_template":    best_tmpl,
        "best_region":      best["region"] if best else None,
        "worst_region":     worst["region"] if worst else None,
        "regions_tried":    regions,
        "templates_tried":  templates,
        "recent_opens":     recent_opens[:50],
        "campaign_details": [
            {
                "campaign_id":   c["campaign_id"],
                "region":        c.get("region"),
                "template":      c.get("template_used"),
                "sent":          c.get("total_sent"),
                "opens":         c.get("total_opens"),
                "open_rate":     f"{c.get('open_rate', 0):.1%}",
                "ga4_installs":  c.get("ga4_installs_delta"),
                "started_at":    c.get("started_at", "")[:10]
            }
            for c in campaigns
        ],
        "data_available": True
    }
