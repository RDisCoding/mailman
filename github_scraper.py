import requests
import csv
import time
import os
from datetime import datetime, timedelta

# Your GitHub Personal Access Token
GITHUB_TOKEN = "YOUR_GITHUB_TOKEN_HERE"

headers = {
    "Accept": "application/vnd.github.v3+json",
}
if GITHUB_TOKEN and GITHUB_TOKEN != "YOUR_GITHUB_TOKEN_HERE":
    headers["Authorization"] = f"token {GITHUB_TOKEN}"

# We want developers who have pushed code in the last 7 days.
# Searching users directly doesn't support 'pushed:', so we search REPOSITORIES 
# that were updated recently, and then extract the repository owners!
last_week = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')

# Example query: Repos pushed in the last 7 days, written in Python, JS, or TS
SEARCH_QUERY = f"pushed:>{last_week} language:python"

def safe_print(text):
    # Safely print to Windows terminal without crashing on emojis/special characters
    print(text.encode('ascii', 'replace').decode('ascii'))

def fetch_active_developers(max_leads=50):
    safe_print(f"Searching for active developers via recent repos: {SEARCH_QUERY}")
    
    leads = []
    seen_users = set()
    page = 1
    
    while len(leads) < max_leads and page <= 100:
        # Sort by updated to get people actively coding RIGHT NOW
        url = f"https://api.github.com/search/repositories?q={SEARCH_QUERY}&sort=updated&order=desc&per_page=30&page={page}"
        response = requests.get(url, headers=headers)
        
        if response.status_code == 403:
            safe_print("API Rate limit hit. Waiting 10 seconds...")
            time.sleep(10)
            continue
            
        data = response.json()
        repos = data.get("items", [])
        
        if not repos:
            break
            
        for repo in repos:
            if len(leads) >= max_leads:
                break
                
            owner = repo.get("owner", {})
            username = owner.get("login")
            
            # Skip organizations and users we've already checked
            if not username or owner.get("type") != "User" or username in seen_users:
                continue
                
            seen_users.add(username)
            
            # Fetch the developer's profile
            profile_url = f"https://api.github.com/users/{username}"
            profile_resp = requests.get(profile_url, headers=headers)
            
            if profile_resp.status_code == 200:
                profile = profile_resp.json()
                email = profile.get("email")
                name = profile.get("name") or username
                company = profile.get("company")
                
                # Only target people with public emails
                if email and "@" in email and "noreply" not in email:
                    institution = company.strip('@') if company else "GitHub"
                    leads.append({
                        "name": name,
                        "email": email,
                        "institution": institution,
                        "template_type": "developer_coding",
                        "status": "not_contacted",
                        "notes": f"Pushed to repo {repo.get('name')} recently"
                    })
                    safe_print(f"Found active dev: {name} | {email} | Just updated: {repo.get('name')}")
            
            time.sleep(0.5) # Rate limit protection
            
        page += 1
        
    return leads

def save_to_csv(leads, filename="active_dev_leads.csv"):
    if not leads:
        safe_print("No leads found with public emails.")
        return
        
    fieldnames = ["name", "email", "institution", "template_type", "status", "notes", "custom_subject", "custom_body"]
    file_exists = os.path.exists(filename)
    
    with open(filename, mode='a', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
            
        for lead in leads:
            for field in fieldnames:
                if field not in lead:
                    lead[field] = ""
            writer.writerow(lead)
            
    safe_print(f"Saved {len(leads)} ultra-active developers to {filename}")

if __name__ == "__main__":
    # Let's pull 500 leads as requested
    found_leads = fetch_active_developers(max_leads=500)
    save_to_csv(found_leads)
