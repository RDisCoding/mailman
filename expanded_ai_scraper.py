import requests
import csv
import time
import os
from dotenv import load_dotenv

load_dotenv()

# --- CONFIGURATION ---
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
headers = {
    "Accept": "application/vnd.github.v3+json",
}
if GITHUB_TOKEN:
    headers["Authorization"] = f"token {GITHUB_TOKEN}"

# Elite Open Source AI Repositories
TARGET_REPOS = [
    "huggingface/transformers",
    "pytorch/pytorch",
    "vllm-project/vllm",
    "langchain-ai/langchain",
    "openai/whisper",
    "tensorflow/tensorflow",
    "karpathy/nanoGPT",
    "deepmind/alphadesign"
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

def fetch_open_source_elite(max_leads=400):
    leads = []
    seen_users = set()

    for repo in TARGET_REPOS:
        if len(leads) >= max_leads:
            break
            
        safe_print(f"\nScanning contributors in: {repo}")
        
        page = 1
        
        while page <= 10:  # Check top 1000 contributors per repo
            url = f"https://api.github.com/repos/{repo}/contributors?per_page=100&page={page}"
            response = requests.get(url, headers=headers)
            
            if check_rate_limit(response):
                continue
                
            if response.status_code != 200:
                safe_print(f"Error fetching repo contributors for {repo}: {response.status_code}")
                break
                
            users = response.json()
            if not users:
                break
                
            for user in users:
                if len(leads) >= max_leads:
                    break
                    
                username = user.get("login")
                if not username or username in seen_users or user.get("type") != "User":
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
                    company = profile.get("company")
                    
                    if email and "@" in email and "noreply" not in email:
                        lead = {
                            "id": f"os_elite_{len(leads)}",
                            "username": username,
                            "profile_url": profile.get("html_url"),
                            "type": profile.get("type", "User"),
                            "email": email,
                            "name": name,
                            "location": profile.get("location", ""),
                            "status": "not_contacted",
                            "notes": f"Top contributor to {repo}. Followers: {profile.get('followers', 0)}",
                            "template_type": "direct",
                            "position": "AI Engineer / OSS Contributor",
                            "institution": company.strip('@') if company else "Open Source AI",
                            "relevant_papers": f"GitHub Followers: {profile.get('followers', 0)}",
                            "research_overlap": f"Core Committer: {repo}",
                            "homepage": profile.get("blog") or profile.get("html_url"),
                            "sources": "Open Source Elite Scraper"
                        }
                        leads.append(lead)
                        safe_print(f"Found Target: {name} | {email} | {repo}")
                        
                        # Append to CSV immediately
                        file_exists = os.path.isfile("open_source_ai_leads.csv")
                        with open("open_source_ai_leads.csv", mode="a", newline="", encoding="utf-8") as f:
                            writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
                            if not file_exists:
                                writer.writeheader()
                            row = {field: lead.get(field, "") for field in FIELDNAMES}
                            writer.writerow(row)
                
                time.sleep(0.05) # Rate limit protection
            page += 1

    return leads

if __name__ == "__main__":
    if not GITHUB_TOKEN:
        print("WARNING: No GITHUB_TOKEN found. The API limit is 60 requests/hour without a token.")
    
    # Remove old file to start fresh
    if os.path.exists("open_source_ai_leads.csv"):
        os.remove("open_source_ai_leads.csv")
        
    safe_print("Commencing mass extraction from Elite AI Repositories...")
    leads = fetch_open_source_elite(max_leads=400)
    safe_print(f"\nDone parsing. Extracted {len(leads)} targets.")
