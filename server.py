import http.server
import socketserver
import json
import os
import csv
import io
import urllib.parse
import threading
import time
import random
import smtplib
from email.mime.text import MIMEText
from email.header import Header

PORT = 8000
DEFAULT_CSV = "github_developers.csv"

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
                    "status": row.get("status", "not_contacted"),
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
    return csv_file

def generate_email_draft(target, template_type):
    # Use custom body/subject if configured via dashboard
    if target.get('custom_subject') and target.get('custom_subject').strip():
        subject = target['custom_subject']
    else:
        university = target.get('institution', 'your university')
        subject = f"Stop starting ChatGPT from scratch at {university}"
        if template_type == 'developer_coding':
            subject = f"ChatGPT context manager for developers at {university}"
        elif template_type == 'general_poweruser':
            subject = "Save and reuse ChatGPT context across tabs"

    if target.get('custom_body') and target.get('custom_body').strip():
        body = target['custom_body']
        is_html = False
    else:
        name = target.get('name') or target.get('username', 'there')
        first_name = name.split(' ')[0]
        if not first_name or not first_name.isalpha() or len(first_name) > 15:
            first_name = "there"
            
        try:
            template_path = os.path.join(os.path.dirname(__file__), "templates", "cortogen_premium.html")
            with open(template_path, "r", encoding="utf-8") as f:
                html_template = f.read()
                
                # Inject personalized greeting
                greeting = f'<div class="content">\n            <p style="font-weight: 600; color: #fff; font-size: 18px; margin-bottom: 20px;">Hi {first_name},</p>'
                personalized_html = html_template.replace('<div class="content">', greeting)
                
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

def run_campaign_thread(csv_file, limit):
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

            template_type = lead.get("template_type", "developer_coding")
            subject, body, is_html = generate_email_draft(lead, template_type)

            campaign_status = f"Sending email {i+1} of {campaign_total} to {name}..."
            log(f"[{i+1}/{campaign_total}] Sending email to {name} ({email_addr}) using template '{template_type}'...")
            
            attempted_count += 1
            try:
                msg_type = 'html' if is_html else 'plain'
                msg = MIMEText(body, msg_type, 'utf-8')
                msg['Subject'] = Header(subject, 'utf-8')
                msg['From'] = Header(f"The Cortogen Team <{sender}>", 'utf-8')
                msg['To'] = Header(email_addr, 'utf-8')
                
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
            
            # Parse limit parameter
            parsed_url = urllib.parse.urlparse(self.path)
            query_params = urllib.parse.parse_qs(parsed_url.query)
            limit = 100
            if 'limit' in query_params:
                try:
                    limit = int(query_params['limit'][0])
                except:
                    pass

            if campaign_running:
                self.send_response(400)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": "Campaign is already running"}).encode('utf-8'))
                return

            # Start thread
            t = threading.Thread(target=run_campaign_thread, args=(csv_file, limit))
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
            
        self.send_response(404)
        self.end_headers()

def run_server():
    # Use socketserver to handle port reuse
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", PORT), OutreachRequestHandler) as httpd:
        print(f"\n==========================================================")
        print(f"  AI Developer Outreach Dashboard is running at:")
        print(f"  http://localhost:{PORT}")
        print(f"==========================================================\n")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down server...")

if __name__ == "__main__":
    run_server()
