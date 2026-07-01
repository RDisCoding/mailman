import requests
import csv
import time
import os
import argparse
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

# --- CONFIGURATION ---

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
headers = {
    "Accept": "application/vnd.github.v3+json",
}
if GITHUB_TOKEN:
    headers["Authorization"] = f"token {GITHUB_TOKEN}"

# Organizations and Universities to target
TARGET_ENTITIES = [
    ("Anthropic", "anthropicai"),
    ("DeepMind", "google-deepmind"),
    ("OpenAI", "openai"),
    ("Meta AI", "facebookresearch"),
    ("Allen Institute for AI", "allenai"),
    ("Mila", "mila-iqia")
]

FIELDNAMES = [
    "id", "username", "profile_url", "type", "email", 
    "name", "location", "status", "notes", "template_type", 
    "position", "institution", "relevant_papers", 
    "research_overlap", "homepage", "sources"
]

def safe_print(text):
    print(text.encode('ascii', 'replace').decode('ascii'), flush=True)

def check_rate_limit(response):
    if response.status_code == 403:
        reset_time = response.headers.get("X-RateLimit-Reset")
        sleep_duration = 60
        if reset_time:
            sleep_duration = max(5, int(reset_time) - int(time.time())) + 2
        safe_print(f"\n[Rate Limit Hit] Sleeping for {sleep_duration} seconds...")
        time.sleep(sleep_duration)
        return True
    return False

def fetch_elite_researchers(max_leads=500):
    leads = []
    seen_users = set()

    for display_name, org_id in TARGET_ENTITIES:
        if len(leads) >= max_leads:
            break
            
        safe_print(f"\nScanning for researchers at: {display_name} ({org_id})")
        
        page = 1
        
        while page <= 10:
            url = f"https://api.github.com/orgs/{org_id}/members?per_page=100&page={page}"
            response = requests.get(url, headers=headers)
            
            if check_rate_limit(response):
                continue
                
            if response.status_code != 200:
                safe_print(f"Error fetching org members for {org_id}: {response.status_code}")
                break
                
            users = response.json()
            
            if not users:
                break
                
            for user in users:
                if len(leads) >= max_leads:
                    break
                    
                username = user.get("login")
                if not username or username in seen_users:
                    continue
                    
                seen_users.add(username)
                
                # Fetch full profile for email
                profile_url = f"https://api.github.com/users/{username}"
                profile_resp = requests.get(profile_url, headers=headers)
                
                if check_rate_limit(profile_resp):
                    time.sleep(2)
                    profile_resp = requests.get(profile_url, headers=headers)
                    
                if profile_resp.status_code == 200:
                    profile = profile_resp.json()
                    email = profile.get("email")
                    name = profile.get("name") or username
                    company = profile.get("company") or display_name
                    
                    if email and "@" in email and "noreply" not in email:
                        lead = {
                            "id": f"elite_{len(leads)}",
                            "username": username,
                            "profile_url": profile.get("html_url"),
                            "type": profile.get("type", "User"),
                            "email": email,
                            "name": name,
                            "location": profile.get("location", ""),
                            "status": "not_contacted",
                            "notes": f"Scraped from elite org: {display_name}. Followers: {profile.get('followers', 0)}",
                            "template_type": "direct", # Use the direct networking template
                            "position": "AI Researcher / Engineer",
                            "institution": company.strip('@') if company else display_name,
                            "relevant_papers": f"GitHub Followers: {profile.get('followers', 0)}",
                            "research_overlap": "Deep Learning & Foundation Models",
                            "homepage": profile.get("blog") or profile.get("html_url"),
                            "sources": "Elite AI Scraper"
                        }
                        leads.append(lead)
                        safe_print(f"Found Elite Target: {name} | {email} | {company}")
                        
                        # Append to CSV immediately
                        file_exists = os.path.isfile("elite_ai_leads.csv")
                        with open("elite_ai_leads.csv", mode="a", newline="", encoding="utf-8") as f:
                            writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
                            if not file_exists:
                                writer.writeheader()
                            row = {field: lead.get(field, "") for field in FIELDNAMES}
                            writer.writerow(row)
                
                time.sleep(0.1) # Faster parsing with token
            page += 1

    return leads

if __name__ == "__main__":
    if not GITHUB_TOKEN:
        print("WARNING: No GITHUB_TOKEN found. The API limit is 60 requests/hour without a token.")
        print("Set it using: $env:GITHUB_TOKEN='your_token'")
    
    # Remove old file to start fresh
    if os.path.exists("elite_ai_leads.csv"):
        os.remove("elite_ai_leads.csv")
        
    fetch_elite_researchers(max_leads=100)
    safe_print("\nDone parsing.")
