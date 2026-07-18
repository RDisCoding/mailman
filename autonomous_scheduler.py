"""
autonomous_scheduler.py
-----------------------
Cortogen's self-driving email scheduler. Three jobs, nothing more:

  Job 1 — Email batch:   Sends emails from your CSV at configured times each day.
  Job 2 — GA4 collect:   Pulls yesterday's GA4 stats at 6am daily.
  Job 3 — Stats report:  Emails you a plain numbers report every 3 days at 7am.

No LLM. No lead generation. You drop the CSV in, the scheduler handles the rest.

Usage:
  python autonomous_scheduler.py            # Start the daemon
  python autonomous_scheduler.py --status   # Show next run times and current CSV
  python autonomous_scheduler.py --report   # Send the stats report right now
  python autonomous_scheduler.py --test     # Send one test email to yourself

Config:  agent_config.json  (copy from agent_config.template.json)
"""

import os
import sys
import json
import time
import threading
from datetime import datetime

try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    import pytz
    SCHEDULER_AVAILABLE = True
except ImportError:
    SCHEDULER_AVAILABLE = False
    print("[Scheduler] WARNING: apscheduler/pytz not installed.")
    print("[Scheduler] Run:  pip install apscheduler pytz")

BASE_DIR        = os.path.dirname(os.path.abspath(__file__))
AGENT_CFG_FILE  = os.path.join(BASE_DIR, "agent_config.json")
CONFIG_FILE     = os.path.join(BASE_DIR, "config.json")

# ── Config ─────────────────────────────────────────────────────────────────────

def load_agent_config() -> dict:
    if not os.path.exists(AGENT_CFG_FILE):
        print(f"[Scheduler] agent_config.json not found.")
        print(f"[Scheduler] Copy agent_config.template.json → agent_config.json and fill it in.")
        return {}
    with open(AGENT_CFG_FILE, "r") as f:
        return json.load(f)

def save_agent_config(cfg: dict):
    with open(AGENT_CFG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)

# ── Job 1: Send Email Batch ────────────────────────────────────────────────────

def job_send_email_batch():
    """
    Reads agent_config.json to find the active CSV, template, and limits,
    then triggers a campaign batch using the existing server.py engine.
    """
    cfg          = load_agent_config()
    active_csv   = cfg.get("active_csv", "")
    template     = cfg.get("active_template", "sales")
    region       = cfg.get("active_region", "Unknown")
    lead_source  = cfg.get("active_lead_source", "Manual CSV")
    daily_limit  = cfg.get("daily_limit_per_window", 30)

    ts = datetime.now().strftime("%H:%M:%S")
    print(f"\n[{ts}] Email batch triggered.")

    if not active_csv:
        print("[Scheduler] No active_csv set in agent_config.json. Skipping.")
        return

    csv_path = os.path.join(BASE_DIR, active_csv)
    if not os.path.exists(csv_path):
        print(f"[Scheduler] CSV not found: {csv_path}")
        print(f"[Scheduler] Drop your CSV into the email agent folder and update active_csv in agent_config.json.")
        return

    print(f"[Scheduler] Sending up to {daily_limit} emails from '{active_csv}' "
          f"using template '{template}'...")

    try:
        from metrics_logger import start_campaign, finish_campaign
        from server import run_campaign_thread

        campaign_id = start_campaign(
            csv_file    = csv_path,
            region      = region,
            lead_source = lead_source,
            template    = template,
            daily_limit = daily_limit,
        )

        def _run():
            run_campaign_thread(csv_path, daily_limit, template, campaign_id=campaign_id)
            # Mark finished (approximation — server.py logs the real count in its summary email)
            finish_campaign(
                campaign_id  = campaign_id,
                total_sent   = daily_limit,
                total_failed = 0,
                notes        = f"Autonomous batch at {datetime.now().isoformat()}"
            )
            print(f"[Scheduler] Batch complete. campaign_id={campaign_id}")

        t = threading.Thread(target=_run, daemon=True)
        t.start()

    except Exception as e:
        print(f"[Scheduler] Failed to start batch: {e}")

# ── Job 2: GA4 Daily Collection ────────────────────────────────────────────────

def job_collect_ga4():
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"\n[{ts}] GA4 collection triggered.")
    try:
        from ga4_collector import append_daily_snapshot
        append_daily_snapshot()
    except Exception as e:
        print(f"[Scheduler] GA4 collection failed: {e}")

# ── Job 3: 3-Day Stats Report ──────────────────────────────────────────────────

def job_send_stats_report():
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"\n[{ts}] 3-day stats report triggered.")
    try:
        from report_mailer import send_report
        send_report(period_days=3)
    except Exception as e:
        print(f"[Scheduler] Stats report failed: {e}")

# ── CLI Commands ───────────────────────────────────────────────────────────────

def cmd_status(scheduler=None):
    cfg = load_agent_config()
    print("\n" + "=" * 55)
    print("  Cortogen Scheduler — Status")
    print("=" * 55)
    print(f"  Active CSV:      {cfg.get('active_csv', 'NOT SET')}")
    print(f"  Template:        {cfg.get('active_template', 'NOT SET')}")
    print(f"  Region:          {cfg.get('active_region', 'NOT SET')}")
    print(f"  Limit/window:    {cfg.get('daily_limit_per_window', 30)} emails")
    print(f"  Send times:      {', '.join(cfg.get('send_times', []))}")
    print(f"  Timezone:        {cfg.get('timezone', 'Asia/Kolkata')}")
    print(f"  Report interval: every {cfg.get('report_interval_days', 3)} days")
    if scheduler:
        print("\n  Scheduled jobs:")
        for job in scheduler.get_jobs():
            nxt = job.next_run_time
            nxt_str = nxt.strftime("%Y-%m-%d %H:%M %Z") if nxt else "not scheduled"
            print(f"    [{job.id}]  next: {nxt_str}")
    print("=" * 55)


def cmd_report():
    print("Sending stats report now...")
    from report_mailer import send_report
    send_report(period_days=3)


def cmd_test():
    """Send one test email to yourself (the notification_email) to verify SMTP works."""
    import smtplib, json
    from email.mime.text import MIMEText
    from email.header import Header

    with open(CONFIG_FILE) as f:
        cfg = json.load(f)

    sender   = cfg.get("sender_email")
    password = cfg.get("app_password")
    notify   = cfg.get("notification_email")
    host     = cfg.get("smtp_host", "smtp.sendgrid.net")
    port     = cfg.get("smtp_port", 465)
    user     = cfg.get("smtp_username", "apikey")

    msg = MIMEText(
        f"Test from Cortogen Scheduler at {datetime.now().isoformat()}.\n\n"
        "If you received this, SMTP is configured correctly.",
        "plain", "utf-8"
    )
    msg["Subject"] = Header("Cortogen Scheduler — Test Email", "utf-8")
    msg["From"]    = Header(f"Cortogen Scheduler <{sender}>", "utf-8")
    msg["To"]      = Header(notify, "utf-8")

    try:
        if port == 587:
            with smtplib.SMTP(host, port) as srv:
                srv.starttls(); srv.login(user, password)
                srv.sendmail(sender, [notify], msg.as_string())
        else:
            with smtplib.SMTP_SSL(host, port) as srv:
                srv.login(user, password)
                srv.sendmail(sender, [notify], msg.as_string())
        print(f"Test email sent to {notify}. Check your inbox.")
    except Exception as e:
        print(f"Test failed: {e}")

# ── Main Daemon ─────────────────────────────────────────────────────────────────

def main():
    # CLI shortcuts
    if "--status" in sys.argv:
        cmd_status()
        return
    if "--report" in sys.argv:
        cmd_report()
        return
    if "--test" in sys.argv:
        cmd_test()
        return

    if not SCHEDULER_AVAILABLE:
        print("Cannot start: apscheduler not installed.")
        print("Run: pip install apscheduler pytz")
        sys.exit(1)

    cfg = load_agent_config()

    tz_str        = cfg.get("timezone", "Asia/Kolkata")
    send_times    = cfg.get("send_times", ["09:00", "14:00"])
    report_days   = cfg.get("report_interval_days", 3)

    try:
        tz = pytz.timezone(tz_str)
    except Exception:
        print(f"[Scheduler] Unknown timezone '{tz_str}'. Defaulting to Asia/Kolkata.")
        tz = pytz.timezone("Asia/Kolkata")

    scheduler = BackgroundScheduler(timezone=tz)

    # ── Job 1: Email batches at configured times ───────────────────────────
    for send_time in send_times:
        try:
            hour, minute = map(int, send_time.split(":"))
            scheduler.add_job(
                job_send_email_batch,
                trigger=CronTrigger(hour=hour, minute=minute, timezone=tz),
                id=f"send_{send_time.replace(':','')}",
                name=f"Email Batch @ {send_time}",
                replace_existing=True,
                misfire_grace_time=600,   # 10-min grace window
            )
        except Exception as e:
            print(f"[Scheduler] Bad send_time '{send_time}': {e}")

    # ── Job 2: GA4 collection every day at 6am ────────────────────────────
    scheduler.add_job(
        job_collect_ga4,
        trigger=CronTrigger(hour=6, minute=0, timezone=tz),
        id="ga4_daily",
        name="GA4 Collection @ 06:00",
        replace_existing=True,
    )

    # ── Job 3: Stats report every N days at 7am ───────────────────────────
    scheduler.add_job(
        job_send_stats_report,
        trigger=CronTrigger(hour=7, minute=0, day=f"*/{report_days}", timezone=tz),
        id="stats_report",
        name=f"Stats Report (every {report_days} days)",
        replace_existing=True,
    )

    scheduler.start()

    # Print status
    print("\n" + "=" * 55)
    print("  Cortogen Autonomous Scheduler — RUNNING")
    print("=" * 55)
    print(f"  Timezone:    {tz_str}")
    print(f"  Send at:     {', '.join(send_times)}")
    print(f"  Report:      every {report_days} days at 07:00")
    print(f"  Active CSV:  {cfg.get('active_csv', 'NOT SET')}")
    print(f"  Template:    {cfg.get('active_template', 'sales')}")
    print(f"  Limit:       {cfg.get('daily_limit_per_window', 30)} emails/window")
    print(f"\n  Jobs:")
    for job in scheduler.get_jobs():
        nxt = job.next_run_time
        nxt_str = nxt.strftime("%Y-%m-%d %H:%M %Z") if nxt else "—"
        print(f"    {job.name:35s}  next: {nxt_str}")
    print(f"\n  Press Ctrl+C to stop.")
    print("=" * 55 + "\n")

    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        print("\n[Scheduler] Stopping...")
        scheduler.shutdown()
        print("[Scheduler] Done.")


if __name__ == "__main__":
    main()
