"""
github_us_scraper.py
--------------------
Scrapes active US-based developers from GitHub using the GitHub REST API.
Targets indie hackers and open-source maintainers — the highest-conversion
audience for developer tools like Cortogen.

Requires:
  - agent_config.json with "github_token" set (PAT with read:user scope)
  - OR environment variable GITHUB_TOKEN

Output: scrapers/us_dev_leads.csv
"""

import os
import csv
import json
import time
import urllib.request
import urllib.error
from datetime import datetime

OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "..", "us_dev_leads.csv")
AGENT_CFG   = os.path.join(os.path.dirname(__file__), "..", "agent_config.json")

FIELDNAMES = [
    "id", "username", "profile_url", "type", "email",
    "name", "location", "status", "notes", "template_type",
    "position", "institution", "relevant_papers",
    "research_overlap", "homepage", "sources"
]

# US cities / locations to search — indie hacker hubs
US_LOCATIONS = [
    "San Francisco", "New York", "Austin", "Seattle",
    "Boston", "Los Angeles", "Chicago", "Denver",
    "Portland", "Atlanta"
]

# ── Config ─────────────────────────────────────────────────────────────────────

def get_github_token():
    if os.path.exists(AGENT_CFG):
        with open(AGENT_CFG) as f:
            cfg = json.load(f)
        token = cfg.get("github_token", "")
        if token:
            return token
    return os.environ.get("GITHUB_TOKEN", "")


def github_get(url: str, token: str) -> dict | None:
    """Make an authenticated GitHub API request."""
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/vnd.github.v3+json")
    req.add_header("User-Agent", "CortogenLeadScraper/1.0")
    if token:
        req.add_header("Authorization", f"token {token}")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 403:
            print(f"[US Scraper] Rate limited. Sleeping 60s...")
            time.sleep(60)
        elif e.code == 422:
            print(f"[US Scraper] Invalid query: {url}")
        else:
            print(f"[US Scraper] HTTP {e.code}: {url}")
        return None
    except Exception as e:
        print(f"[US Scraper] Error: {e}")
        return None

# ── Scraping ───────────────────────────────────────────────────────────────────

def search_users_by_location(location: str, token: str,
                              min_followers: int = 50,
                              max_results: int = 100) -> list:
    """Search GitHub for users in a US city with follower threshold."""
    users = []
    page  = 1

    while len(users) < max_results:
        query = f"location:{location} followers:>{min_followers} type:User"
        url   = (f"https://api.github.com/search/users"
                 f"?q={urllib.parse.quote(query)}&per_page=30&page={page}&sort=followers")

        data = github_get(url, token)
        if not data or "items" not in data:
            break

        items = data.get("items", [])
        if not items:
            break

        users.extend(items)
        page += 1

        # Respect rate limits
        time.sleep(2)

        if len(items) < 30:
            break

    return users[:max_results]


def enrich_user(username: str, token: str) -> dict | None:
    """Fetch full user profile to get email, bio, company, website."""
    data = github_get(f"https://api.github.com/users/{username}", token)
    if not data:
        return None
    time.sleep(0.5)
    return data


def is_indie_hacker(profile: dict) -> bool:
    """
    Heuristic filter: prefer indie hackers / solopreneurs over corp employees.
    Returns True if the profile looks like a good lead.
    """
    company  = (profile.get("company") or "").lower().strip()
    bio      = (profile.get("bio") or "").lower()
    blog     = (profile.get("blog") or "")
    hireable = profile.get("hireable", False)

    # Skip obvious corporate accounts
    corp_signals = ["google", "microsoft", "amazon", "meta", "apple",
                    "netflix", "uber", "stripe", "airbnb", "salesforce"]
    if any(c in company for c in corp_signals):
        return False

    # Positive indie signals
    indie_signals = ["founder", "indie", "solopreneur", "freelance",
                     "side project", "maker", "building", "startup",
                     "open source", "oss", "maintainer", "creator"]
    has_indie = any(s in bio for s in indie_signals)
    has_website = bool(blog and blog.startswith("http"))

    # Must have at least some signal
    return has_indie or has_website or hireable


# ── Main ───────────────────────────────────────────────────────────────────────

def run(output_file: str = None, target_count: int = 300):
    import urllib.parse  # ensure it's available inside run()

    if output_file is None:
        output_file = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "us_dev_leads.csv")
        )

    token = get_github_token()
    if not token:
        print("[US Scraper] WARNING: No GitHub token set. Rate limit will be very low (60 req/hr).")

    print(f"[US Scraper] Targeting {target_count} US developer leads...")

    leads      = []
    seen_users = set()
    lead_id    = 0

    for location in US_LOCATIONS:
        if len(leads) >= target_count:
            break

        print(f"[US Scraper] Searching: {location}...")
        users = search_users_by_location(location, token, min_followers=30, max_results=60)

        for user in users:
            if len(leads) >= target_count:
                break

            username = user.get("login", "")
            if username in seen_users:
                continue
            seen_users.add(username)

            profile = enrich_user(username, token)
            if not profile:
                continue

            email = profile.get("email") or ""
            name  = profile.get("name") or username

            # Skip if no email (can't contact without it)
            if not email or "@" not in email:
                continue

            # Filter for indie hacker profile
            if not is_indie_hacker(profile):
                continue

            lead_id += 1
            leads.append({
                "id":              f"us_dev_{lead_id:04d}",
                "username":        username,
                "profile_url":     profile.get("html_url", ""),
                "type":            "User",
                "email":           email,
                "name":            name,
                "location":        profile.get("location", location),
                "status":          "not_contacted",
                "notes":           (f"GitHub US developer in {location} | "
                                    f"Followers: {profile.get('followers', 0)} | "
                                    f"Repos: {profile.get('public_repos', 0)}"),
                "template_type":   "sales",
                "position":        "Developer",
                "institution":     (profile.get("company") or "Independent").strip("@"),
                "relevant_papers": "",
                "research_overlap":"",
                "homepage":        profile.get("blog", ""),
                "sources":         f"GitHub US Scraper ({location})"
            })
            print(f"[US Scraper] ✓ {name} ({email}) — {location}")

        # Sleep between cities to avoid hammering the API
        time.sleep(3)

    print(f"\n[US Scraper] Found {len(leads)} qualified US leads.")

    # Write CSV
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    with open(output_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(leads)

    print(f"[US Scraper] Saved → {output_file}")
    return output_file


if __name__ == "__main__":
    run(target_count=200)
