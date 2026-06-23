import os
import sys
import json
import time
import random
import smtplib
from email.mime.text import MIMEText
from email.header import Header

CONFIG_FILE = "config.json"
import csv

DATA_FILE = "github_developers.csv"
FIELDNAMES = [
    "id", "username", "profile_url", "type", "email", 
    "name", "location", "status", "notes", "template_type", 
    "custom_subject", "custom_body", "position", "relevant_papers", 
    "research_overlap", "homepage", "sources"
]

def load_config():
    if not os.path.exists(CONFIG_FILE):
        print(f"Error: Configuration file {CONFIG_FILE} not found!")
        print("Please configure your credentials in config.json before running.")
        sys.exit(1)
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def load_targets():
    if not os.path.exists(DATA_FILE):
        return []
    targets = []
    try:
        with open(DATA_FILE, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Map location -> institution for templates
                row['institution'] = row.get('location', 'USA')
                targets.append(row)
    except Exception as e:
        print(f"Error loading {DATA_FILE}: {e}")
    return targets

def save_targets(targets):
    temp_file = DATA_FILE + ".tmp"
    try:
        with open(temp_file, mode='w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
            writer.writeheader()
            for t in targets:
                # Map back institution -> location
                row = {
                    "id": t.get("id", ""),
                    "username": t.get("username", ""),
                    "profile_url": t.get("profile_url", ""),
                    "type": t.get("type", "User"),
                    "email": t.get("email", ""),
                    "name": t.get("name", ""),
                    "location": t.get("institution", "USA"),
                    "status": t.get("status", "not_contacted"),
                    "notes": t.get("notes", ""),
                    "template_type": t.get("template_type", "developer_coding"),
                    "custom_subject": t.get("custom_subject", ""),
                    "custom_body": t.get("custom_body", ""),
                    "position": t.get("position", "Developer"),
                    "relevant_papers": t.get("relevant_papers", ""),
                    "research_overlap": t.get("research_overlap", ""),
                    "homepage": t.get("homepage", ""),
                    "sources": t.get("sources", "GitHub Scraper")
                }
                writer.writerow(row)
        if os.path.exists(DATA_FILE):
            os.remove(DATA_FILE)
        os.rename(temp_file, DATA_FILE)
    except Exception as e:
        print(f"Error saving {DATA_FILE}: {e}")

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
    else:
        first_name = target['name'].split(' ')[0]
        # Safe fallback if name is username-like or empty
        if not first_name or not first_name.isalpha() or len(first_name) > 15:
            first_name = "there"
            
        university = target.get('institution', 'your university')

        if template_type == 'student_study' or template_type == 'adaptive_memory':
            body = f"""Hi {first_name},

As a student at {university}, you probably use ChatGPT regularly for assignments, study guides, and research. 

A common frustration is having to start new conversations from scratch—frequently copy-pasting the same guidelines, course syllabus, or background reference material over and over because ChatGPT's session memory is either stateless or gets bloated.

To solve this, we built Cortogen (https://cortogen.com). It is a free browser extension that adds a local, semantic memory layer to ChatGPT. It automatically captures key context from your active chats and surfaces the most relevant past blocks in real time so you can reuse them in new sessions instantly.

Since you are studying/working at {university}, we would love to get your thoughts on it. It is completely free and secure.

You can try it out here: https://cortogen.com

Best regards,
The Cortogen Team"""

        elif template_type == 'developer_coding' or template_type == 'grpo_rl':
            body = f"""Hi {first_name},

If you use ChatGPT to write, debug, or refactor code for your projects at {university}, you have likely run into its context limitations. 

When starting a new session, you lose your active file structure, instructions, and error logs, forcing you to re-upload files or copy-paste code blocks to get the model back up to speed.

Cortogen (https://cortogen.com) is a free browser extension that solves this by adding a local semantic memory engine to ChatGPT. It automatically indexes code snippets, database schemas, and session context, retrieving them dynamically based on your current prompt so you can reuse them across chat tabs.

It is completely free and helps developers maintain continuous coding sessions without manually re-explaining context.

If you find it useful for your coding workflow, we would love to hear your feedback. Try it here: https://cortogen.com

Best regards,
The Cortogen Team"""

        else:
            body = f"""Hi {first_name},

Standard AI chat interfaces are completely stateless. Every new tab is a clean slate, meaning your custom guidelines, background research, and reference logs are lost, forcing you to re-introduce context repeatedly.

We created Cortogen (https://cortogen.com) to bridge this gap. It is a free, local-first browser extension that provides ChatGPT with long-term memory. It captures important context and semantically retrieves relevant pieces as you type, allowing you to maintain workflow continuity across separate chats.

It is free, secure, and designed to eliminate repetitive prompt preparation.

You can install the extension here: https://cortogen.com

If you have any feedback or suggestions, please let us know.

Best regards,
The Cortogen Team"""

    return subject, body

def send_email(config, recipient_email, subject, body):
    sender = config['sender_email']
    password = config['app_password']
    
    # Create MIME message
    msg = MIMEText(body, 'plain', 'utf-8')
    msg['Subject'] = Header(subject, 'utf-8')
    msg['From'] = Header(f"The Cortogen Team <{sender}>", 'utf-8')
    msg['To'] = Header(recipient_email, 'utf-8')
    
    # Connect and send
    smtp_host = config.get("smtp_host", "smtp.gmail.com")
    smtp_port = config.get("smtp_port", 465)
    
    with smtplib.SMTP_SSL(smtp_host, smtp_port) as server:
        server.login(sender, password)
        server.sendmail(sender, [recipient_email], msg.as_string())

def notify_operator(config, subject, body):
    notify_email = config.get('notification_email')
    if not notify_email or notify_email == "your_notification_email@gmail.com":
        return
    try:
        send_email(config, notify_email, subject, body)
        print(f"Notification sent to operator at: {notify_email}")
    except Exception as e:
        print(f"Failed to send notification: {e}")

def run_campaign_batch(config):
    targets = load_targets()
    
    # Find all not contacted targets
    pending_targets = [t for t in targets if t.get('status') == 'not_contacted']
    
    if not pending_targets:
        print("No pending targets remaining in the list.")
        notify_operator(
            config,
            "Cortogen Campaign Complete!",
            "All targets in the database have been contacted. Please provide a new list of targets."
        )
        return False
        
    daily_quota = min(len(pending_targets), config.get('daily_limit', 50))
    print(f"Starting batch: sending {daily_quota} emails today. Staggering sends to avoid filters...")
    
    sent_count = 0
    for i in range(daily_quota):
        target = pending_targets[i]
        
        # Verify email is present
        email_addr = target.get('email')
        if not email_addr or "@" not in email_addr:
            print(f"Skipping {target['name']} (invalid or missing email: '{email_addr}')")
            # Mark as error/skipped so we don't block the queue
            target['status'] = 'error'
            target['notes'] = "Skipped by automated scheduler: missing/invalid email."
            save_targets(targets)
            continue
            
        template_type = target.get('template_type', 'student_study')
        subject, body = generate_email_draft(target, template_type)
        
        print(f"[{i+1}/{daily_quota}] Sending to {target['name']} ({email_addr}) [{target['institution']}] using template '{template_type}'...")
        
        try:
            send_email(config, email_addr, subject, body)
            target['status'] = 'sent'
            target['notes'] = f"Sent via automated scheduler at {time.strftime('%Y-%m-%d %H:%M:%S')}"
            save_targets(targets)
            sent_count += 1
            
            # Staggered delay (do not sleep after the last email of the batch)
            if i < daily_quota - 1:
                delay = random.randint(config.get('min_delay_seconds', 60), config.get('max_delay_seconds', 120))
                print(f"Email sent successfully. Sleeping for {delay} seconds...")
                time.sleep(delay)
        except Exception as e:
            print(f"Error sending to {target['name']}: {e}")
            target['notes'] = f"Failed send attempt: {e}"
            save_targets(targets)
            
    print(f"\nBatch finished. Successfully sent {sent_count} emails today.")
    return True

def main():
    config = load_config()
    
    # Check if credentials are placeholder
    if config['sender_email'] == "your_gmail_address@gmail.com":
        print("Please configure your actual Gmail SMTP email and App Password in config.json")
        sys.exit(1)
        
    daemon_mode = "--daemon" in sys.argv
    
    if daemon_mode:
        print("Starting Cortogen Outreach Scheduler in DAEMON mode (runs every 24 hours)...")
        while True:
            run_campaign_batch(config)
            print("Going to sleep for 24 hours. Keep this terminal open...")
            time.sleep(24 * 60 * 60)
    else:
        print("Running Cortogen Outreach Scheduler in SINGLE BATCH mode...")
        run_campaign_batch(config)

if __name__ == "__main__":
    main()
