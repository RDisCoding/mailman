import csv
import time
import requests
import os
import argparse

# --- CONFIGURATION ---
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
headers = {
    "Accept": "application/vnd.github.v3+json",
}
if GITHUB_TOKEN:
    headers["Authorization"] = f"token {GITHUB_TOKEN}"


FIELDNAMES = [
    "id", "username", "profile_url", "type", "email", 
    "name", "location", "status", "notes", "template_type", 
    "custom_subject", "custom_body", "position", "relevant_papers", 
    "research_overlap", "homepage", "sources"
]

def load_and_clean_existing(csv_file):
    """Loads existing valid leads, filters out invalid/empty/no_public_email rows, and returns them."""
    valid_leads = []
    seen_usernames = set()
    seen_emails = set()

    if os.path.exists(csv_file):
        try:
            with open(csv_file, mode="r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    username = row.get("username", "").strip()
                    profile_url = row.get("profile_url", "").strip()
                    profile_type = row.get("type", "").strip()
                    email = row.get("email", "").strip()

                    # Only keep rows that have a valid email address
                    if email and "@" in email and email.lower() != "no_public_email" and "noreply" not in email.lower():
                        if username.lower() not in seen_usernames and email.lower() not in seen_emails:
                            # Normalize other fields to avoid blanks
                            lead = {
                                "id": row.get("id") or f"dev_{len(valid_leads)}",
                                "username": username,
                                "profile_url": profile_url,
                                "type": profile_type,
                                "email": email,
                                "name": row.get("name") or username,
                                "location": row.get("location") or "Unknown",
                                "status": row.get("status") or "not_contacted",
                                "notes": row.get("notes") or "",
                                "template_type": row.get("template_type") or "developer_coding",
                                "custom_subject": row.get("custom_subject") or "",
                                "custom_body": row.get("custom_body") or "",
                                "position": row.get("position") or "Developer",
                                "relevant_papers": row.get("relevant_papers") or "Public repositories: 0",
                                "research_overlap": row.get("research_overlap") or "Developer on GitHub",
                                "homepage": row.get("homepage") or profile_url,
                                "sources": row.get("sources") or "GitHub Scraper"
                            }
                            valid_leads.append(lead)
                            seen_usernames.add(username.lower())
                            seen_emails.add(email.lower())
        except Exception as e:
            print(f"Error reading existing CSV: {e}")

    # Immediately write back the cleaned list
    save_to_csv(valid_leads, csv_file)
    return valid_leads, seen_usernames, seen_emails

def save_to_csv(leads, csv_file):
    """Writes the list of leads to the CSV file safely."""
    temp_file = csv_file + ".tmp"
    with open(temp_file, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(leads)
    
    if os.path.exists(csv_file):
        os.remove(csv_file)
    os.rename(temp_file, csv_file)

def check_rate_limit(response):
    """Handles GitHub API rate limits by sleeping if a 403 is encountered."""
    if response.status_code == 403:
        reset_time = response.headers.get("X-RateLimit-Reset")
        sleep_duration = 60
        if reset_time:
            sleep_duration = max(5, int(reset_time) - int(time.time())) + 2
        print(f"\n[Rate Limit Hit] Sleeping for {sleep_duration} seconds...")
        time.sleep(sleep_duration)
        return True
    return False

def main():
    parser = argparse.ArgumentParser(description="GitHub Developer Lead Scraper")
    parser.add_argument("--output", default="github_developers.csv", help="Output CSV file path")
    parser.add_argument("--location", default="USA", help="Target country/location (USA or India)")
    parser.add_argument("--limit", type=int, default=1000, help="Target number of leads to collect")
    args = parser.parse_args()

    csv_file = args.output
    target_location = args.location
    target_count = args.limit

    # Setup location-specific search queries
    if target_location.lower() == "india":
        search_queries = [
            "location:India repos:5..10",
            "location:India repos:11..20",
            "location:India repos:21..50",
            "location:India repos:51..100",
            "location:India repos:>100",
            "location:Bangalore repos:>10",
            "location:Bengaluru repos:>10",
            "location:Hyderabad repos:>10",
            "location:Pune repos:>10",
            "location:Mumbai repos:>10",
            "location:Delhi repos:>10",
            "location:Chennai repos:>10",
            "location:Noida repos:>10",
        ]
    else:
        # Default to USA queries
        search_queries = [
            "location:USA repos:5..10",
            "location:USA repos:11..20",
            "location:USA repos:21..50",
            "location:USA repos:51..100",
            "location:USA repos:>100",
            "location:California repos:>10",
            "location:\"New York\" repos:>10",
            "location:Texas repos:>10",
            "location:Washington repos:>10",
            "location:Massachusetts repos:>10",
            "location:Illinois repos:>10",
            "location:Colorado repos:>10",
        ]

    leads, seen_usernames, seen_emails = load_and_clean_existing(csv_file)
    print(f"Loaded {len(leads)} existing valid developer leads from {csv_file}.")
    print(f"Targeting location: {target_location} (Saving to: {csv_file}, Target Limit: {target_count})")
    
    if len(leads) >= target_count:
        print(f"Target count of {target_count} emails already met!")
        return

    # Start scraping
    for query in search_queries:
        if len(leads) >= target_count:
            break

        print(f"\n--> Starting search query: '{query}'")
        page = 1
        
        while page <= 10:  # GitHub Search API limits to 10 pages (1000 items)
            if len(leads) >= target_count:
                break

            search_url = f"https://api.github.com/search/users?q={query}&page={page}&per_page=100"
            try:
                r = requests.get(search_url, headers=headers)
                if check_rate_limit(r):
                    r = requests.get(search_url, headers=headers)

                if r.status_code != 200:
                    print(f"Search API Error: {r.status_code} {r.text}")
                    break

                results = r.json()
                items = results.get("items", [])
                if not items:
                    print("No more users found in this query.")
                    break

                print(f"Page {page}: Processing {len(items)} users...")

                for item in items:
                    if len(leads) >= target_count:
                        break

                    username = item["login"]
                    profile_url = item["html_url"]
                    profile_type = item["type"]

                    # Skip organizations and already processed usernames
                    if profile_type != "User" or username.lower() in seen_usernames:
                        continue

                    # Fetch detailed profile to check public email
                    detail_url = f"https://api.github.com/users/{username}"
                    try:
                        detail_r = requests.get(detail_url, headers=headers)
                        if check_rate_limit(detail_r):
                            detail_r = requests.get(detail_url, headers=headers)

                        if detail_r.status_code == 200:
                            profile = detail_r.json()
                            public_email = profile.get("email")
                            
                            # Validate public email
                            if public_email and "@" in public_email and "noreply" not in public_email.lower():
                                email_cleaned = public_email.replace(" ", "").strip()
                                
                                if email_cleaned.lower() not in seen_emails:
                                    name = profile.get("name") or username
                                    bio = profile.get("bio") or "Developer on GitHub"
                                    location = profile.get("location") or target_location
                                    blog = profile.get("blog") or profile_url
                                    
                                    # Categorize template type
                                    template_type = "developer_coding"
                                    bio_lower = bio.lower()
                                    if any(x in bio_lower for x in ["ai", "research", "ml", "llm", "nlp"]):
                                        template_type = "general_poweruser"
                                    elif any(x in bio_lower for x in ["student", "university", "college", "study"]):
                                        template_type = "student_study"

                                    lead = {
                                        "id": f"dev_{len(leads)}",
                                        "username": username,
                                        "profile_url": profile_url,
                                        "type": profile_type,
                                        "email": email_cleaned,
                                        "name": name,
                                        "location": location,
                                        "status": "not_contacted",
                                        "notes": "",
                                        "template_type": template_type,
                                        "custom_subject": "",
                                        "custom_body": "",
                                        "position": "Developer",
                                        "relevant_papers": f"Public repositories: {profile.get('public_repos', 0)}",
                                        "research_overlap": bio[:150],
                                        "homepage": blog,
                                        "sources": "GitHub Scraper"
                                    }
                                    leads.append(lead)
                                    seen_usernames.add(username.lower())
                                    seen_emails.add(email_cleaned.lower())
                                    
                                    print(f"  [{len(leads)}/{target_count}] Found: {username} <{email_cleaned}>")
                                    # Save incrementally after finding each email
                                    save_to_csv(leads, csv_file)
                        
                        # Short delay between detailed profile fetches to prevent abuse blocks
                        time.sleep(1.0)

                    except Exception as e:
                        print(f"Error fetching profile for {username}: {e}")
                        time.sleep(2)

                page += 1
                # Short delay between page queries
                time.sleep(2.0)

            except Exception as e:
                print(f"Error during search query: {e}")
                time.sleep(5)
                break

    print(f"\nSuccess! Completed run. Final list contains {len(leads)} developer leads.")

if __name__ == "__main__":
    main()
