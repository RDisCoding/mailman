import http.server
import socketserver
import json
import os
import csv
import io
import base64
import urllib.parse
import urllib.request
import urllib.error
import threading
import time
import random
import smtplib
import sys
from email.mime.text import MIMEText
from email.header import Header

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Metrics logger (graceful fallback if not present)
try:
    from metrics_logger import record_open, start_campaign, finish_campaign
    METRICS_ENABLED = True
except ImportError:
    METRICS_ENABLED = False
    def record_open(email): pass
    def start_campaign(*a, **k): return "no_metrics"
    def finish_campaign(*a, **k): pass

# 1x1 transparent GIF for email tracking pixel
_PIXEL_GIF = base64.b64decode(
    "R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"
)

PORT = int(os.environ.get("PORT", 8000))
DEFAULT_CSV = "active_dev_leads.csv"

FIELDNAMES = [
    "id", "username", "profile_url", "type", "email", 
    "name", "location", "status", "notes", "template_type", 
    "custom_subject", "custom_body", "position", "relevant_papers", 
    "research_overlap", "homepage", "sources"
]

# --- Global Campaign State ---
campaign_lock = threading.Lock()
campaign_running = False
campaign_status = "Idle"
campaign_current = 0
campaign_total = 0
campaign_logs = []
stop_requested = False

def load_csv_as_json(csv_file):
    if not os.path.exists(csv_file):
        return []
    
    leads = []
    try:
        with open(csv_file, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Convert CSV row fields to format expected by frontend
                sources_str = row.get("sources", "GitHub Scraper")
                sources_list = [s.strip() for s in sources_str.split(",") if s.strip()]
                if not sources_list:
                    sources_list = ["GitHub Scraper"]

                status_val = row.get("status", "not_contacted")
                if status_val == "awaiting_orders":
                    status_val = "not_contacted"

                lead = {
                    "id": row.get("id", ""),
                    "username": row.get("username", ""),
                    "profile_url": row.get("profile_url", ""),
                    "type": row.get("type", "User"),
                    "email": row.get("email", ""),
                    "name": row.get("name", ""),
                    "position": row.get("position", "Developer"),
                    "institution": row.get("location", "USA"),  # frontend uses 'institution'
                    "relevant_papers": row.get("relevant_papers", ""),
                    "research_overlap": row.get("research_overlap", ""),
                    "homepage": row.get("homepage", ""),
                    "status": status_val,
                    "notes": row.get("notes", ""),
                    "template_type": row.get("template_type", "developer_coding"),
                    "custom_subject": row.get("custom_subject", ""),
                    "custom_body": row.get("custom_body", ""),
                    "sources": sources_list
                }
                leads.append(lead)
    except Exception as e:
        print(f"Error reading CSV: {e}")
    return leads

def save_json_as_csv(data, csv_file):
    rows = []
    for item in data:
        sources_list = item.get("sources", ["GitHub Scraper"])
        if isinstance(sources_list, list):
            sources_str = ", ".join(sources_list)
        else:
            sources_str = str(sources_list)

        row = {
            "id": item.get("id", ""),
            "username": item.get("username", ""),
            "profile_url": item.get("profile_url", ""),
            "type": item.get("type", "User"),
            "email": item.get("email", ""),
            "name": item.get("name", ""),
            "location": item.get("institution", "USA"),  # frontend 'institution' -> 'location'
            "status": item.get("status", "not_contacted"),
            "notes": item.get("notes", ""),
            "template_type": item.get("template_type", "developer_coding"),
            "custom_subject": item.get("custom_subject", ""),
            "custom_body": item.get("custom_body", ""),
            "position": item.get("position", "Developer"),
            "relevant_papers": item.get("relevant_papers", ""),
            "research_overlap": item.get("research_overlap", ""),
            "homepage": item.get("homepage", ""),
            "sources": sources_str
        }
        rows.append(row)

    temp_file = csv_file + ".tmp"
    with open(temp_file, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    
    if os.path.exists(csv_file):
        os.remove(csv_file)
    os.rename(temp_file, csv_file)

def get_target_file(path):
    """Parse the query parameters to find if a custom csv file is requested."""
    parsed_url = urllib.parse.urlparse(path)
    query_params = urllib.parse.parse_qs(parsed_url.query)
    
    csv_file = DEFAULT_CSV
    if 'file' in query_params:
        requested_file = query_params['file'][0]
        if requested_file.endswith('.csv') and '/' not in requested_file and '\\' not in requested_file:
            csv_file = requested_file

    leads_dir = os.path.join(BASE_DIR, 'leads')
    os.makedirs(leads_dir, exist_ok=True)
    return os.path.join(leads_dir, csv_file)

def _inject_utm(html: str, campaign_id: str, template: str) -> str:
    """
    Replaces bare cortogen.com links with UTM-tagged versions so GA4
    can attribute visits and installs to specific email campaigns.
    """
    import re
    utm = (f"?utm_source=email&utm_medium=cold_email"
           f"&utm_campaign={urllib.parse.quote(campaign_id)}"
           f"&utm_content={urllib.parse.quote(template)}")
    # Replace href="https://cortogen.com" (with or without trailing slash)
    html = re.sub(
        r'href="https://cortogen\.com(/?)"',
        f'href="https://cortogen.com\\1{utm}"',
        html
    )
    return html


def generate_email_draft(target, template_type, campaign_id: str = "manual"):
    # Use custom body/subject if configured via dashboard
    if target.get('custom_subject') and target.get('custom_subject').strip():
        subject = target['custom_subject']
    else:
        subject = "How much time do you spend repeating yourself to ChatGPT?"

    if target.get('custom_body') and target.get('custom_body').strip():
        body = target['custom_body']
        is_html = False
    else:
        name = target.get('name') or target.get('username', 'there')
        first_name = name.split(' ')[0]
        if not first_name or not first_name.isalpha() or len(first_name) > 15:
            first_name = "there"
            
        try:
            if template_type == "premium":
                template_file = "cortogen_premium.html"
            elif template_type == "sales":
                template_file = "cortogen_sales.html"
            else:
                template_file = "cortogen_direct.html"
                
            template_path = os.path.join(os.path.dirname(__file__), "templates", template_file)
            with open(template_path, "r", encoding="utf-8") as f:
                html_template = f.read()
                
                # Inject personalized greeting
                if template_type in ["premium", "sales"]:
                    greeting = f'<div class="content">\n            <p style="font-weight: 600; color: #fff; font-size: 18px; margin-bottom: 20px;">Hi {first_name},</p>'
                    personalized_html = html_template.replace('<div class="content">', greeting)
                else:
                    personalized_html = html_template.replace('{{first_name}}', first_name)
                
                # Inject email for open-tracking pixel
                target_email = target.get('email', '')
                personalized_html = personalized_html.replace('{{email}}', urllib.parse.quote(target_email))

                # Inject UTM parameters into CTA links
                personalized_html = _inject_utm(personalized_html, campaign_id, template_type)

                body = personalized_html
                is_html = True
        except Exception as e:
            print(f"Failed to load HTML template: {e}")
            body = f"Hi {first_name},\n\nPlease check out Cortogen: https://cortogen.com"
            is_html = False

    return subject, body, is_html

def send_summary_email(config, csv_file, attempted, successful, failed, failed_list):
    sender = config.get("sender_email")
    password = config.get("app_password")
    notification = config.get("notification_email")
    
    if not notification or notification == "your_notification_email@gmail.com":
        print("[Summary] Notification email not configured, skipping notification send.")
        return
        
    subject = f"Cortogen Campaign Summary: {os.path.basename(csv_file)}"
    
    failed_details = ""
    if failed_list:
        failed_details = "\nFailed Recipients:\n"
        for name, email, err in failed_list:
            failed_details += f"- {name} <{email}>: {err}\n"
            
    body = f"""Hello,

Your daily batch campaign for {os.path.basename(csv_file)} has completed.

Campaign Run Details:
-----------------------------------------
Date/Time: {time.strftime('%Y-%m-%d %H:%M:%S')}
Database: {csv_file}
Total Attempted: {attempted}
Successfully Sent: {successful}
Failed / Retrying Later: {failed}
-----------------------------------------
{failed_details}
These failed entries have been left as 'not_contacted' in the CSV and will be retried in your next campaign run.

Best regards,
Cortogen Team"""

    try:
        msg = MIMEText(body, 'plain', 'utf-8')
        msg['Subject'] = Header(subject, 'utf-8')
        msg['From'] = Header(f"Cortogen Team <{sender}>", 'utf-8')
        msg['To'] = Header(notification, 'utf-8')
        
        smtp_host = config.get("smtp_host", "smtp.gmail.com")
        smtp_port = config.get("smtp_port", 465)
        smtp_user = config.get("smtp_username", sender)
        
        if smtp_port == 587:
            with smtplib.SMTP(smtp_host, smtp_port) as server:
                server.starttls()
                server.login(smtp_user, password)
                server.sendmail(sender, [notification], msg.as_string())
        else:
            with smtplib.SMTP_SSL(smtp_host, smtp_port) as server:
                server.login(smtp_user, password)
                server.sendmail(sender, [notification], msg.as_string())
        print(f"[Summary] Notification email sent successfully to {notification}.")
    except Exception as e:
        print(f"[Summary] Failed to send notification email: {e}")

def run_campaign_thread(csv_file, limit, selected_template="direct", campaign_id: str = None):
    global campaign_running, campaign_status, campaign_current, campaign_total, campaign_logs, stop_requested
    
    with campaign_lock:
        if campaign_running:
            return
        campaign_running = True
        stop_requested = False
        campaign_logs = []
        campaign_current = 0
        campaign_status = "Initializing campaign..."

    attempted_count = 0
    success_count = 0
    failed_count = 0
    failed_list = []

    def log(msg, log_type="info"):
        t_str = time.strftime('%H:%M:%S')
        campaign_logs.append({"time": t_str, "type": log_type, "message": msg})
        print(f"[{t_str}] [{log_type.upper()}] {msg}")

    try:
        # Load config
        if not os.path.exists("config.json"):
            log("Error: config.json not found!", "error")
            campaign_status = "Error: config.json not found"
            campaign_running = False
            return
            
        with open("config.json", "r", encoding="utf-8") as f:
            config = json.load(f)
            
        sender = config.get("sender_email")
        password = config.get("app_password")
        if not sender or sender == "your_gmail_address@gmail.com":
            log("Error: Gmail credentials not configured in config.json!", "error")
            campaign_status = "Error: SMTP credentials not set"
            campaign_running = False
            return

        log(f"Loading leads from {csv_file}...")
        leads = load_csv_as_json(csv_file)
        
        pending = [lead for lead in leads if lead.get("status") == "not_contacted"]
        daily_limit = config.get("daily_limit", limit)
        campaign_total = min(len(pending), daily_limit)
        
        if campaign_total == 0:
            log("No pending ('not_contacted') leads found in this list.", "info")
            campaign_status = "Finished: No pending leads"
            campaign_running = False
            return

        # Use provided campaign_id or generate one for metrics tracking
        if not campaign_id:
            campaign_id = f"manual_{time.strftime('%Y_%m_%d_%H%M')}"

        log(f"Found {len(pending)} pending leads. Sending batch of {campaign_total} emails today.")

        for i in range(campaign_total):
            if stop_requested:
                log("Campaign stopped by user request.", "info")
                campaign_status = "Stopped by user"
                break
                
            lead = pending[i]
            username = lead.get("username")
            email_addr = lead.get("email")
            name = lead.get("name") or username
            
            if not email_addr or "@" not in email_addr:
                log(f"Skipping {name} (invalid or missing email: '{email_addr}')", "error")
                lead["status"] = "error"
                lead["notes"] = "Skipped by automated web campaign: missing/invalid email."
                save_json_as_csv(leads, csv_file)
                campaign_current += 1
                continue

            lead["template_type"] = selected_template
            template_type = lead.get("template_type", "direct")
            subject, body, is_html = generate_email_draft(lead, template_type, campaign_id=campaign_id)

            campaign_status = f"Sending email {i+1} of {campaign_total} to {name}..."
            log(f"[{i+1}/{campaign_total}] Sending email to {name} ({email_addr}) using template '{template_type}'...")
            
            attempted_count += 1
            try:
                msg_type = 'html' if is_html else 'plain'
                msg = MIMEText(body, msg_type, 'utf-8')
                msg['Subject'] = Header(subject, 'utf-8')
                msg['From'] = Header(f"The Cortogen Team <{sender}>", 'utf-8')
                msg['To'] = Header(email_addr, 'utf-8')
                
                reply_to = config.get("reply_to_email")
                if reply_to:
                    msg['Reply-To'] = Header(reply_to, 'utf-8')
                
                smtp_host = config.get("smtp_host", "smtp.gmail.com")
                smtp_port = config.get("smtp_port", 465)
                smtp_user = config.get("smtp_username", sender)
                
                if smtp_port == 587:
                    with smtplib.SMTP(smtp_host, smtp_port) as server:
                        server.starttls()
                        server.login(smtp_user, password)
                        server.sendmail(sender, [email_addr], msg.as_string())
                else:
                    with smtplib.SMTP_SSL(smtp_host, smtp_port) as server:
                        server.login(smtp_user, password)
                        server.sendmail(sender, [email_addr], msg.as_string())
                
                lead["status"] = "sent"
                lead["notes"] = f"Sent via automated web campaign at {time.strftime('%Y-%m-%d %H:%M:%S')}"
                save_json_as_csv(leads, csv_file)
                campaign_current += 1
                success_count += 1
                log(f"Email successfully sent to {name}.", "success")
                
            except Exception as e:
                log(f"Error sending to {name}: {e}", "error")
                lead["notes"] = f"Failed send attempt: {e}"
                save_json_as_csv(leads, csv_file)
                campaign_current += 1
                failed_count += 1
                failed_list.append((name, email_addr, str(e)))

            # Sleep between emails unless it was the last one
            if i < campaign_total - 1 and not stop_requested:
                min_delay = config.get("min_delay_seconds", 60)
                max_delay = config.get("max_delay_seconds", 120)
                delay = random.randint(min_delay, max_delay)
                log(f"Waiting for {delay} seconds before next send...", "info")
                
                for seconds_left in range(delay, 0, -1):
                    if stop_requested:
                        break
                    campaign_status = f"Staggering sends... Next email in {seconds_left}s"
                    time.sleep(1)
                    
        if stop_requested:
            campaign_status = "Stopped"
        else:
            log("Campaign batch complete!", "success")
            campaign_status = "Finished"

        # Send Campaign Summary Notification
        log(f"Sending campaign summary email to {config.get('notification_email')}...")
        send_summary_email(config, csv_file, attempted_count, success_count, failed_count, failed_list)

        if campaign_id:
            try:
                finish_campaign(campaign_id, success_count, failed_count, f"Completed with {success_count} sent.")
            except:
                pass

    except Exception as e:
        log(f"Fatal error in campaign thread: {e}", "error")
        campaign_status = f"Error: {e}"
    finally:
        campaign_running = False

class OutreachRequestHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        # Allow CORS for development ease
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        # Force mobile browsers to never cache index.html or API routes
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200, "OK")
        self.end_headers()

    def do_GET(self):
        # API Route: Fetch all researchers
        if self.path.startswith('/api/researchers'):
            csv_file = get_target_file(self.path)
            
            self.send_response(200)
            self.send_header('Content-type', 'application/json; charset=utf-8')
            self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
            self.send_header('Pragma', 'no-cache')
            self.send_header('Expires', '0')
            self.end_headers()
            
            leads = load_csv_as_json(csv_file)
            self.wfile.write(json.dumps(leads).encode('utf-8'))
            return

        # API Route: Email open tracking pixel
        if self.path.startswith('/api/track/open'):
            parsed = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed.query)
            email  = urllib.parse.unquote(params.get('email', [''])[0])

            # Log the open in metrics
            if email and METRICS_ENABLED:
                threading.Thread(target=record_open, args=(email,), daemon=True).start()

            # Return 1x1 transparent GIF
            self.send_response(200)
            self.send_header('Content-Type', 'image/gif')
            self.send_header('Content-Length', str(len(_PIXEL_GIF)))
            self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate')
            self.send_header('Pragma', 'no-cache')
            self.end_headers()
            self.wfile.write(_PIXEL_GIF)
            return

        # API Route: Fetch current campaign status
        if self.path == '/api/campaign-status':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            
            status_data = {
                "running": campaign_running,
                "status": campaign_status,
                "current": campaign_current,
                "total": campaign_total,
                "logs": campaign_logs
            }
            self.wfile.write(json.dumps(status_data).encode('utf-8'))
            return
            
        # API Route: Fetch analytics (local metrics + remote stats)
        if self.path == '/api/analytics':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()

            combined = {"total_opens": 0, "unique_opens": 0, "recent_opens": [], "campaigns": []}

            # Local campaign metrics
            if METRICS_ENABLED:
                try:
                    from metrics_logger import summarize_performance, get_last_n_campaigns
                    perf = summarize_performance(days=7)
                    combined["total_opens"]   = perf.get("total_opens", 0)
                    combined["avg_open_rate"] = perf.get("avg_open_rate", 0)
                    combined["campaigns"]     = perf.get("campaign_details", [])
                except Exception as le:
                    combined["local_metrics_error"] = str(le)

            # Remote stats (best-effort)
            try:
                req = urllib.request.Request(
                    'https://api.cortogen.com/api/admin/email-stats',
                    headers={'X-Admin-Key': 'CORTOGEN_ADMIN_SECURE_123'}
                )
                with urllib.request.urlopen(req, timeout=5) as response:
                    remote = json.loads(response.read())
                    combined["recent_opens"]  = remote.get("recent_opens", [])
                    combined["remote_stats"]  = remote
            except Exception:
                pass  # silently ignore if offline

            self.wfile.write(json.dumps(combined).encode('utf-8'))
            return
            
        # Default: Serve static files
        if self.path == '/' or self.path == '':
            self.path = '/index.html'
            
        return super().do_GET()

    def do_POST(self):
        # API Route: Save all researchers
        if self.path.startswith('/api/researchers'):
            csv_file = get_target_file(self.path)
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            
            try:
                # Validate JSON structure before saving
                data = json.loads(post_data.decode('utf-8'))
                save_json_as_csv(data, csv_file)
                
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "success", "message": f"Saved {len(data)} developers to {csv_file}"}).encode('utf-8'))
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))
            return

        # API Route: Start Campaign Batch
        if self.path.startswith('/api/send-batch'):
            csv_file = get_target_file(self.path)
            
            # Parse limit and template parameter
            parsed_url = urllib.parse.urlparse(self.path)
            query_params = urllib.parse.parse_qs(parsed_url.query)
            limit = 100
            if 'limit' in query_params:
                try:
                    limit = int(query_params['limit'][0])
                except:
                    pass
                    
            selected_template = "direct"
            if 'template' in query_params:
                selected_template = query_params['template'][0]

            if campaign_running:
                self.send_response(400)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": "Campaign is already running"}).encode('utf-8'))
                return

            # Start thread
            def manual_runner():
                try:
                    c_id = start_campaign(csv_file, "Manual", "UI", selected_template, limit)
                except:
                    c_id = None
                run_campaign_thread(csv_file, limit, selected_template, campaign_id=c_id)

            t = threading.Thread(target=manual_runner)
            t.daemon = True
            t.start()

            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"status": "success", "message": f"Campaign started for {csv_file} with limit of {limit}"}).encode('utf-8'))
            return

        # API Route: Stop Campaign
        if self.path == '/api/stop-campaign':
            global stop_requested
            stop_requested = True
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"status": "success", "message": "Stop requested"}).encode('utf-8'))
            return

        # API Route: Start Scheduler Daemon
        if self.path == '/api/scheduler/start':
            try:
                import subprocess
                # Start as background process, redirecting I/O to avoid stream init errors
                log_path = os.path.join(BASE_DIR, 'scheduler.log')
                log_file = open(log_path, 'a')
                
                creationflags = 0
                if os.name == 'nt':
                    creationflags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
                
                proc = subprocess.Popen(
                    [sys.executable, "autonomous_scheduler.py"], 
                    cwd=BASE_DIR,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    creationflags=creationflags
                )
                pid_file = os.path.join(BASE_DIR, 'scheduler.pid')
                with open(pid_file, 'w') as f:
                    f.write(str(proc.pid))
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok", "pid": proc.pid}).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode())
            return

        # API Route: Stop Scheduler Daemon
        if self.path == '/api/scheduler/stop':
            try:
                pid_file = os.path.join(BASE_DIR, 'scheduler.pid')
                if os.path.exists(pid_file):
                    with open(pid_file) as f:
                        pid = int(f.read().strip())
                    import signal
                    # Windows specific kill
                    if os.name == 'nt':
                        os.kill(pid, signal.SIGTERM)
                    else:
                        os.kill(pid, signal.SIGKILL)
                    os.remove(pid_file)
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok"}).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode())
            return

        # API Route: Get/Set agent config
        if self.path == '/api/agent-config':
            agent_cfg_path = os.path.join(BASE_DIR, 'agent_config.json')
            if not os.path.exists(agent_cfg_path):
                # Create from template defaults
                default_cfg = {
                    "timezone": "Asia/Kolkata",
                    "send_times": ["09:00", "14:00"],
                    "daily_limit_per_window": 30,
                    "report_interval_days": 3,
                    "active_csv": "",
                    "active_template": "sales",
                    "active_region": "",
                    "active_lead_source": "Manual CSV",
                    "ga4_property_id": ""
                }
                with open(agent_cfg_path, 'w') as f:
                    json.dump(default_cfg, f, indent=2)
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            try:
                new_cfg = json.loads(post_data.decode('utf-8'))
                with open(agent_cfg_path, 'w') as f:
                    json.dump(new_cfg, f, indent=2)
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok"}).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode())
            return

        # API Route: Send stats report now
        if self.path == '/api/send-report':
            try:
                from report_mailer import send_report
                import threading as _t
                _t.Thread(target=send_report, args=(3,), daemon=True).start()
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok", "message": "Report email queued."}).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode())
            return

        # API Route: Save template
        if self.path == '/api/templates':
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            try:
                data = json.loads(post_data.decode('utf-8'))
                name = data.get('name')
                content = data.get('content')
                if name and content:
                    templates_dir = os.path.join(BASE_DIR, 'templates')
                    os.makedirs(templates_dir, exist_ok=True)
                    if not name.endswith('.html') and not name.endswith('.txt'):
                        name += '.html'
                    with open(os.path.join(templates_dir, name), 'w', encoding='utf-8') as f:
                        f.write(content)
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok"}).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode())
            return

        self.send_response(404)
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        # API Route: Get agent config
        if path == '/api/agent-config':
            agent_cfg_path = os.path.join(BASE_DIR, 'agent_config.json')
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            if os.path.exists(agent_cfg_path):
                with open(agent_cfg_path, 'r') as f:
                    self.wfile.write(f.read().encode())
            else:
                default = {
                    "timezone": "Asia/Kolkata",
                    "send_times": ["09:00", "14:00"],
                    "daily_limit_per_window": 30,
                    "report_interval_days": 3,
                    "active_csv": "",
                    "active_template": "sales",
                    "active_region": "",
                    "active_lead_source": "Manual CSV",
                    "ga4_property_id": ""
                }
                self.wfile.write(json.dumps(default).encode())
            return

        # API Route: Upload CSV
        if path == '/api/upload-csv':
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            try:
                data = json.loads(post_data.decode('utf-8'))
                name = data.get('name')
                content = data.get('content')
                if name and content:
                    leads_dir = os.path.join(BASE_DIR, 'leads')
                    os.makedirs(leads_dir, exist_ok=True)
                    if not name.endswith('.csv'):
                        name += '.csv'
                    with open(os.path.join(leads_dir, name), 'w', encoding='utf-8') as f:
                        f.write(content)
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok"}).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode())
            return

        # API Route: List available CSV files
        if path == '/api/list-csvs':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            leads_dir = os.path.join(BASE_DIR, 'leads')
            os.makedirs(leads_dir, exist_ok=True)
            csvs = [f for f in os.listdir(leads_dir) if f.endswith('.csv')]
            self.wfile.write(json.dumps(csvs).encode())
            return

        # API Route: List available templates
        if path == '/api/list-templates':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            templates_dir = os.path.join(BASE_DIR, 'templates')
            os.makedirs(templates_dir, exist_ok=True)
            templates = [f for f in os.listdir(templates_dir) if f.endswith('.html') or f.endswith('.txt')]
            self.wfile.write(json.dumps(templates).encode())
            return

        # API Route: Scheduler status (check if autonomous_scheduler is running)
        if path == '/api/scheduler/status':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            # Check for pid file
            pid_file = os.path.join(BASE_DIR, 'scheduler.pid')
            running = False
            pid = None
            jobs = []
            if os.path.exists(pid_file):
                try:
                    with open(pid_file) as f:
                        pid = int(f.read().strip())
                    import signal
                    os.kill(pid, 0)  # Check if process alive
                    
                    jobs_file = os.path.join(BASE_DIR, 'scheduler_jobs.json')
                    mtime_pid = os.path.getmtime(pid_file)
                    is_booting = (time.time() - mtime_pid) < 15

                    if os.path.exists(jobs_file):
                        mtime = os.path.getmtime(jobs_file)
                        # Check heartbeat: file should be updated every 15s by daemon
                        if not is_booting and (time.time() - mtime > 45):
                            running = False # Daemon crashed and stopped updating heartbeat
                        else:
                            running = True
                            with open(jobs_file) as jf:
                                jobs = json.load(jf)
                    else:
                        if not is_booting:
                            running = False # Failed to start properly
                        else:
                            running = True # Still initializing
                            
                except Exception:
                    running = False
            self.wfile.write(json.dumps({"running": running, "pid": pid, "jobs": jobs}).encode())
            return

        # Existing GET routes (researchers, tracking pixel, campaign-status, analytics)
        if self.path.startswith('/api/researchers'):
            csv_file = get_target_file(self.path)
            self.send_response(200)
            self.send_header('Content-type', 'application/json; charset=utf-8')
            self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
            self.send_header('Pragma', 'no-cache')
            self.send_header('Expires', '0')
            self.end_headers()
            leads = load_csv_as_json(csv_file)
            self.wfile.write(json.dumps(leads).encode('utf-8'))
            return

        if self.path.startswith('/api/track/open'):
            parsed = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed.query)
            email  = urllib.parse.unquote(params.get('email', [''])[0])
            if email and METRICS_ENABLED:
                threading.Thread(target=record_open, args=(email,), daemon=True).start()
            self.send_response(200)
            self.send_header('Content-Type', 'image/gif')
            self.send_header('Content-Length', str(len(_PIXEL_GIF)))
            self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate')
            self.send_header('Pragma', 'no-cache')
            self.end_headers()
            self.wfile.write(_PIXEL_GIF)
            return

        if path == '/api/campaign-status':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            status_data = {
                "running": campaign_running,
                "status": campaign_status,
                "current": campaign_current,
                "total": campaign_total,
                "logs": campaign_logs
            }
            self.wfile.write(json.dumps(status_data).encode('utf-8'))
            return

        if path == '/api/analytics':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            combined = {"total_opens": 0, "unique_opens": 0, "recent_opens": [], "campaigns": [], "avg_open_rate": 0}
            if METRICS_ENABLED:
                try:
                    from metrics_logger import summarize_performance
                    from ga4_collector import compute_ga4_delta
                    perf = summarize_performance(days=7)
                    ga4  = compute_ga4_delta(days=7)
                    combined.update({
                        "total_opens":    perf.get("total_opens", 0),
                        "avg_open_rate":  perf.get("avg_open_rate", 0),
                        "campaigns":      perf.get("campaign_details", []),
                        "total_sent":     perf.get("total_sent", 0),
                        "campaigns_run":  perf.get("campaigns_run", 0),
                        "ga4_new_users":  ga4.get("total_new_users", 0),
                        "ga4_installs":   ga4.get("total_installs", 0),
                        "ga4_sessions":   ga4.get("total_sessions", 0),
                    })
                except Exception as e:
                    combined["error"] = str(e)
            try:
                req = urllib.request.Request(
                    'https://api.cortogen.com/api/admin/email-stats',
                    headers={'X-Admin-Key': 'CORTOGEN_ADMIN_SECURE_123'}
                )
                with urllib.request.urlopen(req, timeout=5) as response:
                    remote = json.loads(response.read())
                    combined["recent_opens"] = remote.get("recent_opens", [])
                    combined["unique_opens"] = remote.get("unique_opens", 0)
            except Exception:
                pass
            self.wfile.write(json.dumps(combined).encode('utf-8'))
            return

        # Default: serve static files
        if path == '/' or path == '':
            self.path = '/index.html'
        return super().do_GET()


def run_server():
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", PORT), OutreachRequestHandler) as httpd:
        print(f"\n==========================================================")
        print(f"  Cortogen Email Dashboard running at:")
        print(f"  http://localhost:{PORT}")
        print(f"==========================================================\n")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down server...")

if __name__ == "__main__":
    run_server()
