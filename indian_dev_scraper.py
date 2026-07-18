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

# Target Indian tech hubs and location strings
LOCATIONS = [
    "Bangalore", "Bengaluru", "Hyderabad", "Pune", "Mumbai", 
    "Delhi", "Noida", "Gurgaon", "Chennai", "India"
]

FIELDNAMES = [
    "id", "username", "profile_url", "type", "email", 
    "name", "location", "status", "notes", "template_type", 
    "position", "institution", "relevant_papers", 
    "research_overlap", "homepage", "sources"
]

MAX_LEADS = 300  # Target number of leads

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

def scrape_indian_devs():
    leads = []
    seen_users = set()
    lead_count = 0
    
    # Start fresh by removing old output file
    if os.path.exists("indian_dev_leads.csv"):
        os.remove("indian_dev_leads.csv")
        safe_print("Removed old indian_dev_leads.csv. Starting fresh.")

    for loc in LOCATIONS:
        if lead_count >= MAX_LEADS:
            break
            
        safe_print(f"\nScanning active developers in location: {loc}")
        
        # Paginate through search results (up to 10 pages)
        page = 1
        while page <= 10:
            if lead_count >= MAX_LEADS:
                break
                
            # Search query: location, followers filter (to ensure active developers), and sorted by followers
            url = f"https://api.github.com/search/users?q=location:{loc}+followers:>10&sort=followers&order=desc&per_page=100&page={page}"
            response = requests.get(url, headers=headers)
            
            if check_rate_limit(response):
                continue
                
            if response.status_code != 200:
                safe_print(f"Error fetching users for location {loc}: {response.status_code}")
                break
                
            search_data = response.json()
            users = search_data.get("items", [])
            if not users:
                break
                
            for user in users:
                if lead_count >= MAX_LEADS:
                    break
                    
                username = user.get("login")
                if not username or username in seen_users or user.get("type") != "User":
                    continue
                    
                seen_users.add(username)
                
                # Fetch full profile details to retrieve public email
                profile_url = f"https://api.github.com/users/{username}"
                profile_resp = requests.get(profile_url, headers=headers)
                
                if check_rate_limit(profile_resp):
                    time.sleep(2)
                    profile_resp = requests.get(profile_url, headers=headers)
                    
                if profile_resp.status_code == 200:
                    profile = profile_resp.json()
                    email = profile.get("email")
                    
                    # We only care about users with public, valid emails
                    if email and "@" in email and "noreply" not in email.lower():
                        lead_count += 1
                        name = profile.get("name") or username
                        company = profile.get("company") or "Open Source"
                        location = profile.get("location") or loc
                        followers = profile.get("followers", 0)
                        
                        lead = {
                            "id": f"in_dev_{lead_count:03d}",
                            "username": username,
                            "profile_url": profile.get("html_url"),
                            "type": "User",
                            "email": email,
                            "name": name,
                            "location": location,
                            "status": "not_contacted",
                            "notes": f"GitHub developer in {location} | Followers: {followers}",
                            "template_type": "sales",
                            "position": "Developer",
                            "institution": company,
                            "relevant_papers": "",
                            "research_overlap": "",
                            "homepage": profile.get("blog") or profile.get("html_url"),
                            "sources": "Indian Developer Scraper"
                        }
                        
                        leads.append(lead)
                        safe_print(f"[{lead_count}/{MAX_LEADS}] Found: {name} ({email}) | Followers: {followers} | Location: {location}")
                        
                        # Write to CSV in real-time
                        file_exists = os.path.isfile("indian_dev_leads.csv")
                        with open("indian_dev_leads.csv", mode="a", newline="", encoding="utf-8") as f:
                            writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
                            if not file_exists:
                                writer.writeheader()
                            row = {field: lead.get(field, "") for field in FIELDNAMES}
                            writer.writerow(row)
                            
                # Micro sleep to be gentle on GitHub API
                time.sleep(0.1)
                
            page += 1
            
    safe_print(f"\nScraping complete. Generated {lead_count} leads in indian_dev_leads.csv.")
    return leads

if __name__ == "__main__":
    if not GITHUB_TOKEN:
        print("WARNING: No GITHUB_TOKEN found. The API limit is extremely restricted without a token.")
    
    scrape_indian_devs()
