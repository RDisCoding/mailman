import requests
import json
import csv
import time
import os
import re

def safe_print(text):
    try:
        print(text.encode('ascii', 'replace').decode('ascii'))
    except:
        pass

def extract_email(text):
    if not text:
        return None, None
    # Sometimes it's "Name <email@domain.com>"
    match = re.search(r'([^<]+)<\s*([^>]+)\s*>', text)
    if match:
        return match.group(1).strip(), match.group(2).strip()
    
    # Or just an email
    if '@' in text:
        parts = text.split(',')
        for part in parts:
            part = part.strip()
            if '@' in part and ' ' not in part:
                return "Developer", part
                
    return None, None

def scrape_pypi(max_leads=100):
    safe_print("Fetching top PyPI packages list...")
    try:
        res = requests.get('https://hugovk.github.io/top-pypi-packages/top-pypi-packages-30-days.min.json', timeout=10)
        data = res.json()
        packages = [row['project'] for row in data['rows']]
    except Exception as e:
        safe_print(f"Failed to fetch package list: {e}")
        return []

    leads = []
    seen_emails = set()
    
    safe_print(f"Found {len(packages)} top packages. Extracting author details...")
    
    for pkg in packages:
        if len(leads) >= max_leads:
            break
            
        pkg_url = f'https://pypi.org/pypi/{pkg}/json'
        try:
            r = requests.get(pkg_url, timeout=5)
            if r.status_code != 200:
                continue
            
            info = r.json().get('info', {})
            author_email_raw = info.get('author_email') or info.get('maintainer_email')
            
            if not author_email_raw:
                continue
                
            name, email = extract_email(author_email_raw)
            
            if not email:
                email = author_email_raw if '@' in author_email_raw and ' ' not in author_email_raw else None
                name = info.get('author') or info.get('maintainer') or "Developer"
                
            if email:
                email = email.lower().strip()
                # Filter out generic/org emails
                if 'no-reply' in email or 'noreply' in email or 'bot@' in email or 'support@' in email:
                    continue
                    
                if email not in seen_emails:
                    seen_emails.add(email)
                    
                    if name == "Developer" or not name:
                        name = pkg.title() + " Author"
                    
                    # Clean up name if it's too weird
                    name = name.replace('"', '').replace("'", "").strip()
                        
                    leads.append({
                        "name": name,
                        "email": email,
                        "institution": "Open Source (PyPI)",
                        "template_type": "developer_coding",
                        "status": "awaiting_orders",
                        "notes": f"Author/Maintainer of top Python package '{pkg}'",
                        "custom_subject": "",
                        "custom_body": ""
                    })
                    safe_print(f"[{len(leads)}/{max_leads}] Found: {name} <{email}> from package {pkg}")
                    
        except Exception as e:
            continue
            
        # Polite delay
        time.sleep(0.1)
        
    return leads

def save_to_csv(leads, filename="pypi_dev_leads.csv"):
    if not leads:
        safe_print("No leads found.")
        return
        
    fieldnames = ["id", "username", "profile_url", "type", "email", "name", "institution", "status", "notes", "template_type", "custom_subject", "custom_body", "position", "relevant_papers", "research_overlap", "homepage", "sources"]
    file_exists = os.path.exists(filename)
    
    with open(filename, mode='a', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
            
        for idx, lead in enumerate(leads):
            full_lead = {
                "id": f"pypi_{int(time.time())}_{idx}",
                "username": lead["email"].split('@')[0],
                "profile_url": "",
                "type": "User",
                "email": lead["email"],
                "name": lead["name"],
                "institution": lead["institution"],
                "status": lead["status"],
                "notes": lead["notes"],
                "template_type": lead["template_type"],
                "custom_subject": "",
                "custom_body": "",
                "position": "Open Source Contributor",
                "relevant_papers": "",
                "research_overlap": "",
                "homepage": "",
                "sources": "PyPI Top Packages"
            }
            writer.writerow(full_lead)
            
    safe_print(f"Saved {len(leads)} high-profile Python developers to {filename}")

if __name__ == "__main__":
    found_leads = scrape_pypi(max_leads=150)
    save_to_csv(found_leads)
