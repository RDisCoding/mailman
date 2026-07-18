"""
report_mailer.py
----------------
Sends a plain stats report email every 3 days.
No LLM. No suggestions. Just the numbers from the last 3 days:
  - Emails sent / failed / open rate
  - GA4: new users, installs, sessions
  - Per-campaign breakdown

Called automatically by autonomous_scheduler.py.
Can also be run manually:  python report_mailer.py
"""

import os
import json
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")


def load_smtp_config() -> dict:
    with open(CONFIG_FILE, "r") as f:
        return json.load(f)


def build_report_html(perf: dict, ga4: dict) -> str:
    """Build a clean, no-frills stats HTML email."""

    # Campaign rows
    campaigns   = perf.get("campaign_details", [])
    camp_rows   = ""
    for c in campaigns:
        rate_pct = f"{float(c.get('open_rate', '0%').rstrip('%')):.1f}%" \
            if isinstance(c.get("open_rate"), str) else f"{c.get('open_rate', 0):.1%}"
        camp_rows += f"""
        <tr>
          <td>{c.get('started_at','')[:10]}</td>
          <td>{c.get('region','—')}</td>
          <td>{c.get('template','—')}</td>
          <td style="text-align:center">{c.get('sent', 0)}</td>
          <td style="text-align:center">{c.get('opens', 0)}</td>
          <td style="text-align:center;font-weight:600;color:#FFB703">{c.get('open_rate','0%')}</td>
          <td style="text-align:center">{c.get('ga4_installs', 0)}</td>
        </tr>"""

    if not camp_rows:
        camp_rows = """<tr><td colspan="7" style="text-align:center;color:#555;padding:20px">
            No campaigns run in this period.</td></tr>"""

    # Totals
    total_sent   = perf.get("total_sent", 0)
    total_opens  = perf.get("total_opens", 0)
    avg_rate     = perf.get("avg_open_rate", 0)
    avg_rate_pct = f"{avg_rate:.1%}"

    ga4_users    = ga4.get("total_new_users", 0)
    ga4_sessions = ga4.get("total_sessions", 0)
    ga4_installs = ga4.get("total_installs", 0)
    ga4_bounce   = f"{ga4.get('avg_bounce_rate', 0):.1%}"
    ga4_source   = ga4.get("data_available", False)

    ga4_note     = "" if ga4_source else (
        "<p style='color:#888;font-size:12px;margin-top:8px'>"
        "GA4 data not yet configured (service_account.json missing). "
        "See README for setup.</p>"
    )

    # Open rate colour
    if avg_rate >= 0.20:
        rate_color = "#00c864"   # green — good
    elif avg_rate >= 0.10:
        rate_color = "#FFB703"   # amber — okay
    else:
        rate_color = "#ff5050"   # red — likely spam

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
  body {{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
         background:#0f0f0f;color:#e0e0e0;margin:0;padding:0}}
  .wrap {{max-width:660px;margin:0 auto;padding:32px 24px}}
  .header {{border-bottom:1px solid rgba(251,133,0,0.35);padding-bottom:18px;margin-bottom:24px}}
  .badge {{display:inline-block;background:linear-gradient(135deg,#FFB703,#FB8500);
           color:#000;font-size:11px;font-weight:700;padding:4px 10px;
           border-radius:12px;letter-spacing:1px;text-transform:uppercase}}
  h1 {{font-size:22px;font-weight:700;color:#fff;margin:10px 0 4px}}
  .meta {{font-size:13px;color:#555}}
  .stats-grid {{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-bottom:24px}}
  .stat-box {{background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.07);
              border-radius:10px;padding:18px 16px;text-align:center}}
  .stat-val {{font-size:28px;font-weight:700;color:#FFB703;margin-bottom:4px}}
  .stat-lbl {{font-size:12px;color:#666;letter-spacing:0.5px;text-transform:uppercase}}
  .section {{background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.07);
             border-radius:10px;padding:20px 22px;margin-bottom:18px}}
  .section h2 {{font-size:13px;font-weight:700;color:#FB8500;letter-spacing:1px;
                text-transform:uppercase;margin:0 0 14px}}
  table {{width:100%;border-collapse:collapse;font-size:13px}}
  th {{color:#666;font-size:11px;letter-spacing:0.5px;text-transform:uppercase;
       padding:6px 8px;border-bottom:1px solid rgba(255,255,255,0.07);text-align:left}}
  td {{padding:10px 8px;border-bottom:1px solid rgba(255,255,255,0.04);color:#c0c0c0}}
  .footer {{text-align:center;padding-top:22px;border-top:1px solid rgba(255,255,255,0.06);
            font-size:12px;color:#444;margin-top:8px}}
</style>
</head>
<body>
<div class="wrap">

  <div class="header">
    <div class="badge">3-Day Stats Report</div>
    <h1>Cortogen Campaign Report</h1>
    <div class="meta">Period ending {datetime.now().strftime('%A, %B %d, %Y')}
      &nbsp;&middot;&nbsp; {perf.get('campaigns_run', 0)} campaign(s) run</div>
  </div>

  <!-- Top-line stats -->
  <div class="stats-grid">
    <div class="stat-box">
      <div class="stat-val">{total_sent}</div>
      <div class="stat-lbl">Emails Sent</div>
    </div>
    <div class="stat-box">
      <div class="stat-val">{total_opens}</div>
      <div class="stat-lbl">Total Opens</div>
    </div>
    <div class="stat-box">
      <div class="stat-val" style="color:{rate_color}">{avg_rate_pct}</div>
      <div class="stat-lbl">Avg Open Rate</div>
    </div>
  </div>

  <!-- GA4 -->
  <div class="section">
    <h2>Google Analytics (Last 3 Days)</h2>
    <div class="stats-grid" style="margin-bottom:0">
      <div class="stat-box">
        <div class="stat-val" style="font-size:22px">{ga4_users}</div>
        <div class="stat-lbl">New Users</div>
      </div>
      <div class="stat-box">
        <div class="stat-val" style="font-size:22px">{ga4_installs}</div>
        <div class="stat-lbl">Installs</div>
      </div>
      <div class="stat-box">
        <div class="stat-val" style="font-size:22px">{ga4_sessions}</div>
        <div class="stat-lbl">Sessions</div>
      </div>
    </div>
    {ga4_note}
  </div>

  <!-- Campaign breakdown -->
  <div class="section">
    <h2>Campaign Breakdown</h2>
    <table>
      <thead>
        <tr>
          <th>Date</th><th>Region</th><th>Template</th>
          <th style="text-align:center">Sent</th>
          <th style="text-align:center">Opens</th>
          <th style="text-align:center">Rate</th>
          <th style="text-align:center">Installs</th>
        </tr>
      </thead>
      <tbody>{camp_rows}</tbody>
    </table>
  </div>

  <div class="footer">
    <strong style="color:#FB8500">CORTOGEN</strong> Autonomous Scheduler
    &nbsp;&middot;&nbsp; Giving AI a memory.<br>
    Next report in ~3 days.
  </div>
</div>
</body>
</html>"""


def send_report(period_days: int = 3):
    """Fetch stats, build HTML, and send the report email."""
    try:
        from metrics_logger import summarize_performance
        from ga4_collector  import compute_ga4_delta
    except ImportError as e:
        print(f"[Report] Import error: {e}")
        return False

    perf = summarize_performance(days=period_days)
    ga4  = compute_ga4_delta(days=period_days)

    cfg      = load_smtp_config()
    sender   = cfg.get("sender_email")
    password = cfg.get("app_password")
    notify   = cfg.get("notification_email", "rudraydave@gmail.com")
    host     = cfg.get("smtp_host", "smtp.sendgrid.net")
    port     = cfg.get("smtp_port", 465)
    user     = cfg.get("smtp_username", "apikey")

    if not sender or not password:
        print("[Report] SMTP config missing. Cannot send report.")
        return False

    subject = (f"Cortogen Stats — "
               f"{datetime.now().strftime('%b %d')} "
               f"| {perf.get('total_sent', 0)} sent "
               f"| {perf.get('avg_open_rate', 0):.1%} open rate")

    html = build_report_html(perf, ga4)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"]    = Header(f"Cortogen Scheduler <{sender}>", "utf-8")
    msg["To"]      = Header(notify, "utf-8")
    msg.attach(MIMEText(html, "html", "utf-8"))

    try:
        if port == 587:
            with smtplib.SMTP(host, port) as srv:
                srv.starttls()
                srv.login(user, password)
                srv.sendmail(sender, [notify], msg.as_string())
        else:
            with smtplib.SMTP_SSL(host, port) as srv:
                srv.login(user, password)
                srv.sendmail(sender, [notify], msg.as_string())

        print(f"[Report] Stats email sent to {notify}")
        print(f"[Report] Summary: {perf.get('total_sent',0)} sent | "
              f"{perf.get('total_opens',0)} opens | "
              f"{perf.get('avg_open_rate',0):.1%} open rate | "
              f"{ga4.get('total_installs',0)} GA4 installs")
        return True

    except Exception as e:
        print(f"[Report] Failed to send: {e}")
        return False


if __name__ == "__main__":
    print("Sending 3-day stats report...")
    success = send_report(period_days=3)
    if not success:
        print("Report failed. Check config.json SMTP settings.")
