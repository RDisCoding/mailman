"""
buyer_intent_scraper.py
-----------------------
Finds HIGH-INTENT buyers for Cortogen — people who actively use ChatGPT,
Claude, or Gemini and have already felt the "losing context" pain.

The Logic (why these people are buyers, not just lookers):
==========================================================

CORTOGEN's ideal buyer is someone who:
  1. Uses AI tools (ChatGPT/Claude/Gemini) HEAVILY — not casually
  2. Has felt the frustration of losing context across sessions
  3. Is technical enough to install a Chrome extension
  4. Has autonomy to adopt new tools (not locked in corporate process)

SOURCE STRATEGY — We look for signals that PROVE they are AI power users:

  Signal A: "AI Builder" — Their GitHub repos import openai, anthropic,
            langchain, etc. as dependencies. These people BUILD with LLMs
            daily. They experience the memory problem professionally.

  Signal B: "AI Power User" — They've starred repos related to AI memory,
            context, prompt management. People star things they WISH they had.

  Signal C: "AI Prompter" — Their repos have topics/descriptions about
            prompt engineering, LLM workflows, GPT automation.

  Signal D: "Recency" — Active in the last 6 months (not dormant accounts)

  Signal E: "Reachable" — Has a public email set on their GitHub profile

SCORING MODEL (0–100 buyer score):
  +30  has repos using openai/anthropic/langchain (they BUILD with AI)
  +20  has repos using openai specifically (most relevant to Cortogen)
  +15  starred AI memory or context management tools
  +15  bio mentions AI, GPT, Claude, LLM, prompt
  +10  active in last 3 months (pushed code recently)
  +10  has personal website (higher autonomy, more likely early adopter)
  +5   indie/freelance (no corporate gatekeeping)
  -20  works at Google/Microsoft/Meta/Apple (corporate = slow adoption)
  -10  no repos (inactive / just a follower)

Only leads with score >= 40 are included in the output.
This score is stored in the CSV so the brain can learn which score ranges
actually convert (GA4 installs) and improve the threshold over time.

SELF-IMPROVEMENT:
  The strategy_brain.py reads conversion data and calls the LLM which can
  suggest adjusting MIN_BUYER_SCORE or which signals to weight more heavily.
  The brain saves updated weights to buyer_score_config.json which this
  scraper reads on next run.
"""

import os
import csv
import json
import time
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime, timezone

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(BASE_DIR)
AGENT_CFG  = os.path.join(PARENT_DIR, "agent_config.json")
SCORE_CFG  = os.path.join(PARENT_DIR, "buyer_score_config.json")

# ── Scoring weights (overridable by LLM brain via buyer_score_config.json) ────

DEFAULT_WEIGHTS = {
    "uses_openai_api":          25,   # requires.openai in dependencies
    "uses_anthropic_api":       20,   # requires.anthropic
    "uses_langchain":           15,   # langchain / llm orchestration
    "uses_other_ai_lib":        10,   # huggingface, ollama, litellm etc
    "starred_ai_memory_tool":   20,   # starred tools like mem0, memgpt, etc.
    "bio_mentions_ai":          15,   # bio has gpt/claude/llm/prompt
    "has_ai_topic_repo":        10,   # repo topics: chatgpt, llm, prompt-engineering
    "active_last_3_months":     10,   # pushed code recently
    "has_personal_website":     10,   # personal site = higher autonomy
    "is_indie_or_freelance":    5,    # no corporate gatekeeping
    "many_public_repos":        5,    # 10+ repos = serious developer
    "penalty_big_corp":        -20,   # google, ms, meta, apple
    "penalty_no_repos":        -10,   # 0 repos = just a viewer
}

DEFAULT_MIN_SCORE = 40  # Only include leads above this threshold

# AI libraries that prove someone builds with LLMs
AI_DEPENDENCY_SIGNALS = {
    "openai":       "uses_openai_api",
    "anthropic":    "uses_anthropic_api",
    "langchain":    "uses_langchain",
    "langchain-core": "uses_langchain",
    "llama-index":  "uses_other_ai_lib",
    "llamaindex":   "uses_other_ai_lib",
    "litellm":      "uses_other_ai_lib",
    "transformers": "uses_other_ai_lib",
    "ollama":       "uses_other_ai_lib",
    "groq":         "uses_other_ai_lib",
    "mistralai":    "uses_other_ai_lib",
    "cohere":       "uses_other_ai_lib",
    "huggingface_hub": "uses_other_ai_lib",
    "@anthropic-ai": "uses_anthropic_api",
    "openai-node":  "uses_openai_api",
    "openai-python": "uses_openai_api",
}

# AI memory / context tools on GitHub — people who starred these WANT what Cortogen provides
AI_MEMORY_REPOS = [
    "mem0ai/mem0",
    "cpacker/MemGPT",
    "tatsu-lab/stanford_alpaca",
    "run-llama/llama_index",
    "hwchase17/langchain",
    "langchain-ai/langchain",
    "openai/openai-python",
    "Significant-Gravitas/AutoGPT",
    "lm-sys/FastChat",
    "PromtEngineer/localGPT",
    "imartinez/privateGPT",
    "lobehub/lobe-chat",
    "mckaywrigley/chatbot-ui",
    "f/awesome-chatgpt-prompts",
    "dair-ai/Prompt-Engineering-Guide",
]

# GitHub repo topics that signal AI power users
AI_TOPICS = {
    "chatgpt", "gpt-4", "gpt-3", "openai", "claude", "anthropic",
    "llm", "large-language-model", "prompt-engineering", "langchain",
    "ai-assistant", "llama", "generative-ai", "gpt", "rag",
    "retrieval-augmented-generation", "ai-memory", "context-window",
    "llm-applications", "ai-workflow", "chatbot", "conversational-ai"
}

CORP_PENALTIES = [
    "google", "microsoft", "amazon", "meta", "apple", "netflix",
    "uber", "stripe", "airbnb", "salesforce", "oracle", "ibm",
    "vmware", "twitter", "linkedin", "adobe", "nvidia"
]

BIO_AI_SIGNALS = [
    "gpt", "chatgpt", "claude", "llm", "ai", "prompt", "langchain",
    "openai", "anthropic", "llama", "gemini", "deep learning",
    "machine learning", "nlp", "generative", "neural", "transformer"
]


# ── Config loading ─────────────────────────────────────────────────────────────

def load_weights() -> tuple[dict, int]:
    """Load scoring weights from brain-updated config, or use defaults."""
    if os.path.exists(SCORE_CFG):
        try:
            with open(SCORE_CFG) as f:
                cfg = json.load(f)
            weights  = cfg.get("weights", DEFAULT_WEIGHTS)
            min_score = cfg.get("min_buyer_score", DEFAULT_MIN_SCORE)
            print(f"[Scraper] Loaded custom scoring weights from buyer_score_config.json "
                  f"(min_score={min_score})")
            return weights, min_score
        except Exception:
            pass
    return DEFAULT_WEIGHTS, DEFAULT_MIN_SCORE

def get_github_token() -> str:
    if os.path.exists(AGENT_CFG):
        with open(AGENT_CFG) as f:
            cfg = json.load(f)
        return cfg.get("github_token", "")
    return os.environ.get("GITHUB_TOKEN", "")

# ── GitHub API helpers ─────────────────────────────────────────────────────────

def github_get(url: str, token: str, retries: int = 3) -> dict | None:
    for attempt in range(retries):
        req = urllib.request.Request(url)
        req.add_header("Accept", "application/vnd.github.v3+json")
        req.add_header("User-Agent", "CortogenBuyerScraper/2.0")
        if token:
            req.add_header("Authorization", f"token {token}")
        try:
            with urllib.request.urlopen(req, timeout=12) as resp:
                # Check rate limit headers
                remaining = resp.headers.get("X-RateLimit-Remaining", "999")
                if int(remaining) < 10:
                    reset_ts = int(resp.headers.get("X-RateLimit-Reset", time.time() + 60))
                    wait = max(0, reset_ts - int(time.time())) + 5
                    print(f"[Scraper] Rate limit low ({remaining} remaining). "
                          f"Waiting {wait}s...")
                    time.sleep(wait)
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 403:
                print("[Scraper] Rate limited (403). Sleeping 60s...")
                time.sleep(60)
            elif e.code == 404:
                return None
            elif e.code == 422:
                return None
            else:
                print(f"[Scraper] HTTP {e.code} for {url}")
                if attempt < retries - 1:
                    time.sleep(5)
        except Exception as e:
            print(f"[Scraper] Request error: {e}")
            if attempt < retries - 1:
                time.sleep(3)
    return None


def get_user_repos(username: str, token: str, max_repos: int = 30) -> list:
    """Get public repos for a user."""
    url  = (f"https://api.github.com/users/{username}/repos"
            f"?per_page={max_repos}&sort=pushed&type=owner")
    data = github_get(url, token)
    return data if isinstance(data, list) else []


def get_repo_contents(username: str, repo: str, token: str) -> list | None:
    """Get root file listing of a repo."""
    url = f"https://api.github.com/repos/{username}/{repo}/contents"
    return github_get(url, token)


def get_file_content(username: str, repo: str, path: str, token: str) -> str:
    """Download a specific file from a repo and return its text content."""
    import base64
    url  = f"https://api.github.com/repos/{username}/{repo}/contents/{path}"
    data = github_get(url, token)
    if not data or data.get("encoding") != "base64":
        return ""
    try:
        return base64.b64decode(data["content"]).decode("utf-8", errors="ignore")
    except Exception:
        return ""


# ── Core: Buyer Signals Detection ─────────────────────────────────────────────

def detect_ai_dependencies(username: str, repos: list, token: str) -> set:
    """
    Scan repos for AI library dependencies (requirements.txt, package.json,
    pyproject.toml, Pipfile). Returns set of matched signal keys.
    """
    signals_found = set()
    dependency_files = {
        "requirements.txt", "requirements-dev.txt", "requirements_dev.txt",
        "pyproject.toml", "Pipfile", "package.json", "package-lock.json",
        "setup.py", "setup.cfg", "environment.yml"
    }

    # Only check top 10 most recently pushed repos (efficiency)
    for repo in repos[:10]:
        if signals_found:
            # Already found strong signals — no need to scan more repos
            break

        repo_name = repo.get("name", "")
        if repo.get("fork"):
            continue  # Skip forks — not their own code

        # First check repo topics (fast, no extra API call)
        topics = set(repo.get("topics", []))
        for topic in topics:
            if topic in AI_TOPICS:
                signals_found.add("has_ai_topic_repo")
                break

        # Check repo description for AI keywords
        desc = (repo.get("description") or "").lower()
        if any(kw in desc for kw in ["gpt", "llm", "claude", "openai", "langchain", "prompt"]):
            signals_found.add("has_ai_topic_repo")

        # Fetch root file listing to find dependency files
        contents = get_repo_contents(username, repo_name, token)
        if not contents or not isinstance(contents, list):
            time.sleep(0.3)
            continue

        root_files = {f["name"].lower(): f["name"] for f in contents
                      if f.get("type") == "file"}

        for dep_file_lower, dep_file_actual in root_files.items():
            if dep_file_lower not in dependency_files:
                continue
            if signals_found.issuperset({"uses_openai_api", "uses_anthropic_api"}):
                break

            content = get_file_content(username, repo_name, dep_file_actual, token)
            if not content:
                continue

            content_lower = content.lower()
            for lib, signal in AI_DEPENDENCY_SIGNALS.items():
                if lib in content_lower and signal not in signals_found:
                    signals_found.add(signal)
                    print(f"  [Signal] {username}: found '{lib}' in {repo_name}/{dep_file_actual}")

        time.sleep(0.5)

    return signals_found


def check_bio_signals(profile: dict) -> set:
    """Detect AI power user signals in GitHub bio and profile."""
    signals = set()
    bio     = (profile.get("bio") or "").lower()

    if any(kw in bio for kw in BIO_AI_SIGNALS):
        signals.add("bio_mentions_ai")

    return signals


def check_activity_signals(profile: dict) -> set:
    """Detect recency and activity signals."""
    signals = set()

    # Recently pushed (updated_at on profile is somewhat unreliable;
    # we use repos[0].pushed_at via the repos list)
    pub_repos = profile.get("public_repos", 0)
    if pub_repos >= 10:
        signals.add("many_public_repos")
    elif pub_repos == 0:
        signals.add("penalty_no_repos")

    blog = (profile.get("blog") or "")
    if blog and blog.startswith("http"):
        signals.add("has_personal_website")

    company = (profile.get("company") or "").lower().strip("@ ")
    if any(c in company for c in CORP_PENALTIES):
        signals.add("penalty_big_corp")

    hireable = profile.get("hireable", False)
    if hireable:
        signals.add("is_indie_or_freelance")

    bio  = (profile.get("bio") or "").lower()
    indie_words = ["freelance", "indie", "solopreneur", "founder", "maker",
                   "building", "self-employed", "consultant", "contractor"]
    if any(w in bio for w in indie_words):
        signals.add("is_indie_or_freelance")

    return signals


def check_repo_recency(repos: list) -> set:
    """Check if user has pushed code in the last 3 months."""
    signals = set()
    if not repos:
        return signals

    cutoff = datetime.now(timezone.utc)
    from datetime import timedelta
    three_months_ago = cutoff - timedelta(days=90)

    for repo in repos[:5]:
        pushed = repo.get("pushed_at", "")
        if not pushed:
            continue
        try:
            pushed_dt = datetime.fromisoformat(pushed.replace("Z", "+00:00"))
            if pushed_dt > three_months_ago:
                signals.add("active_last_3_months")
                break
        except Exception:
            continue

    return signals


# ── Scoring Engine ─────────────────────────────────────────────────────────────

def compute_buyer_score(all_signals: set, weights: dict) -> tuple[int, dict]:
    """
    Compute a 0-100 buyer score and return which signals fired.
    Returns (score, signal_breakdown).
    """
    breakdown = {}
    total     = 0

    for signal, points in weights.items():
        if signal in all_signals:
            breakdown[signal] = points
            total += points

    # Clamp to 0-100
    score = max(0, min(100, total))
    return score, breakdown


def describe_signals(breakdown: dict) -> str:
    """Human-readable explanation of why this person scored high."""
    parts = []
    positive_map = {
        "uses_openai_api":          "builds with OpenAI API",
        "uses_anthropic_api":       "builds with Anthropic/Claude API",
        "uses_langchain":           "uses LangChain",
        "uses_other_ai_lib":        "uses AI libraries (HuggingFace/Ollama/etc)",
        "starred_ai_memory_tool":   "starred AI memory tools",
        "bio_mentions_ai":          "AI-focused bio",
        "has_ai_topic_repo":        "has AI/LLM topic repos",
        "active_last_3_months":     "active coder (last 3 months)",
        "has_personal_website":     "personal website",
        "is_indie_or_freelance":    "indie/freelance",
        "many_public_repos":        "10+ public repos",
    }
    for signal, pts in breakdown.items():
        if pts > 0 and signal in positive_map:
            parts.append(positive_map[signal])
    return " | ".join(parts) if parts else "general developer"


# ── Search Strategies ─────────────────────────────────────────────────────────

def search_ai_repo_owners(token: str, max_per_query: int = 100) -> list:
    """
    Strategy A: Find people who OWN repos that use AI libraries.
    Searches for repos with 'openai' or 'langchain' in the name/description,
    then gets the repo owners.
    This is the highest-intent signal — these people BUILT AI tools.
    """
    queries = [
        "openai in:name,description language:python stars:>5 pushed:>2024-01-01",
        "langchain in:name,description language:python stars:>5 pushed:>2024-01-01",
        "anthropic claude in:name,description pushed:>2024-01-01",
        "llm memory in:name,description stars:>3 pushed:>2024-01-01",
        "chatgpt wrapper in:name,description pushed:>2024-01-01",
        "prompt engineering in:name,description pushed:>2024-01-01",
        "gpt4 tool in:name,description stars:>5 pushed:>2024-01-01",
        "ai assistant chrome extension in:name,description pushed:>2024-01-01",
    ]

    owners = set()
    for query in queries:
        url = (f"https://api.github.com/search/repositories"
               f"?q={urllib.parse.quote(query)}&per_page=30&sort=updated")
        data = github_get(url, token)
        if not data or "items" not in data:
            time.sleep(2)
            continue

        for repo in data.get("items", []):
            owner = repo.get("owner", {})
            if owner.get("type") == "User":
                owners.add(owner.get("login", ""))

        time.sleep(2)

    print(f"[Scraper] Strategy A: found {len(owners)} AI repo owners")
    return list(owners)[:max_per_query]


def search_topic_users(token: str, max_per_query: int = 80) -> list:
    """
    Strategy B: Find repos tagged with AI topics and get their owners.
    GitHub topics are deliberately chosen by the developer — very high signal.
    """
    topics = [
        "openai", "chatgpt", "langchain", "llm", "prompt-engineering",
        "gpt-4", "anthropic", "llm-applications", "ai-assistant",
        "generative-ai", "rag", "retrieval-augmented-generation"
    ]

    owners = set()
    for topic in topics[:6]:  # limit to avoid rate limits
        url = (f"https://api.github.com/search/repositories"
               f"?q=topic:{topic}+pushed:>2024-06-01+stars:>2"
               f"&per_page=30&sort=updated")
        data = github_get(url, token)
        if not data or "items" not in data:
            time.sleep(2)
            continue

        for repo in data.get("items", []):
            owner = repo.get("owner", {})
            if owner.get("type") == "User":
                owners.add(owner.get("login", ""))

        time.sleep(2)

    print(f"[Scraper] Strategy B: found {len(owners)} topic-matched repo owners")
    return list(owners)[:max_per_query]


# ── Main Pipeline ──────────────────────────────────────────────────────────────

FIELDNAMES = [
    "id", "username", "profile_url", "type", "email",
    "name", "location", "status", "notes", "template_type",
    "position", "institution", "relevant_papers",
    "research_overlap", "homepage", "sources",
    "buyer_score", "buyer_signals"   # NEW: for self-improvement tracking
]


def run(output_file: str = None, target_count: int = 200):
    """
    Main scraping pipeline. Produces buyer-intent-scored leads.

    Stages:
      1. Discover candidate usernames via AI repo ownership (Strategy A + B)
      2. For each candidate:
         a. Fetch full profile
         b. Fetch repos
         c. Detect AI dependency signals in repo code
         d. Detect bio/activity/recency signals
         e. Compute buyer score
         f. Skip if score < min_threshold
      3. Sort by score descending
      4. Save to CSV with buyer_score column

    The buyer_score column allows the strategy brain to correlate
    "who actually opened/installed" with score ranges over time.
    """

    if output_file is None:
        output_file = os.path.normpath(
            os.path.join(PARENT_DIR, "ai_buyer_leads.csv")
        )

    token    = get_github_token()
    weights, min_score = load_weights()

    if not token:
        print("[Scraper] WARNING: No GitHub token. Rate limit = 60 req/hr.")
        print("[Scraper] Add 'github_token' to agent_config.json for 5000 req/hr.")

    print(f"\n{'='*60}")
    print(f"  Cortogen Buyer-Intent Scraper v2.0")
    print(f"  Target: {target_count} leads | Min buyer score: {min_score}")
    print(f"{'='*60}\n")

    # Stage 1: Discover candidates
    print("[Scraper] Stage 1: Discovering AI-active users...")
    candidates_a = search_ai_repo_owners(token, max_per_query=120)
    candidates_b = search_topic_users(token, max_per_query=100)

    all_candidates = list(set(candidates_a + candidates_b))
    print(f"[Scraper] Total unique candidates: {len(all_candidates)}")

    # Stage 2: Enrich and score each candidate
    print(f"\n[Scraper] Stage 2: Scoring {len(all_candidates)} candidates...")
    scored_leads = []
    seen         = set()

    for i, username in enumerate(all_candidates):
        if len(scored_leads) >= target_count * 3:
            # Collected enough candidates, stop enriching
            break

        if username in seen:
            continue
        seen.add(username)

        print(f"\n[{i+1}/{len(all_candidates)}] Analyzing: {username}")

        # Fetch profile
        profile = github_get(f"https://api.github.com/users/{username}", token)
        if not profile:
            continue

        email = (profile.get("email") or "").strip()
        name  = (profile.get("name") or username).strip()

        if not email or "@" not in email:
            print(f"  [Skip] No public email")
            time.sleep(0.3)
            continue

        # Fetch repos
        repos = get_user_repos(username, token, max_repos=30)
        time.sleep(0.5)

        # Detect signals
        signals = set()
        signals |= check_bio_signals(profile)
        signals |= check_activity_signals(profile)
        signals |= check_repo_recency(repos)
        signals |= detect_ai_dependencies(username, repos, token)

        # Score
        score, breakdown = compute_buyer_score(signals, weights)

        print(f"  [Score] {score}/100 | Signals: {', '.join(signals) if signals else 'none'}")

        if score < min_score:
            print(f"  [Skip] Score {score} < threshold {min_score}")
            continue

        reason = describe_signals(breakdown)
        scored_leads.append({
            "profile":    profile,
            "email":      email,
            "name":       name,
            "username":   username,
            "score":      score,
            "signals":    signals,
            "breakdown":  breakdown,
            "reason":     reason,
            "repos":      repos,
        })
        print(f"  [KEEP] {name} ({email}) — score={score} — {reason}")

        time.sleep(1)

    # Stage 3: Sort by buyer score descending, take top N
    print(f"\n[Scraper] Stage 3: Sorting {len(scored_leads)} qualified leads by buyer score...")
    scored_leads.sort(key=lambda x: x["score"], reverse=True)
    final_leads = scored_leads[:target_count]

    # Stage 4: Write CSV
    rows = []
    for idx, lead in enumerate(final_leads):
        profile  = lead["profile"]
        company  = (profile.get("company") or "Independent").strip("@ ")

        rows.append({
            "id":              f"ai_buyer_{idx+1:04d}",
            "username":        lead["username"],
            "profile_url":     profile.get("html_url", ""),
            "type":            "User",
            "email":           lead["email"],
            "name":            lead["name"],
            "location":        profile.get("location", ""),
            "status":          "not_contacted",
            "notes":           (f"Buyer score: {lead['score']}/100 | "
                                f"{lead['reason']} | "
                                f"Followers: {profile.get('followers', 0)} | "
                                f"Repos: {profile.get('public_repos', 0)}"),
            "template_type":   "sales",
            "position":        "Developer",
            "institution":     company,
            "relevant_papers": "",
            "research_overlap": lead["reason"],
            "homepage":        profile.get("blog", ""),
            "sources":         "Buyer-Intent Scraper v2.0",
            "buyer_score":     lead["score"],
            "buyer_signals":   "|".join(sorted(lead["signals"]))
        })

    with open(output_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    # Summary
    avg_score = sum(r["buyer_score"] for r in rows) / len(rows) if rows else 0
    print(f"\n{'='*60}")
    print(f"  DONE: {len(rows)} buyer-intent leads saved")
    print(f"  Average buyer score: {avg_score:.1f}/100")
    print(f"  Output: {output_file}")
    print(f"{'='*60}\n")

    # Save a summary for the strategy brain to read
    summary = {
        "run_at":          datetime.now().isoformat(),
        "total_candidates": len(all_candidates),
        "total_scored":    len(scored_leads),
        "total_saved":     len(rows),
        "avg_buyer_score": round(avg_score, 1),
        "min_score_used":  min_score,
        "weights_used":    weights,
        "output_file":     output_file,
    }
    with open(os.path.join(PARENT_DIR, "metrics", "last_scrape_summary.json"), "w") as f:
        json.dump(summary, f, indent=2)

    return output_file


if __name__ == "__main__":
    import sys
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 150
    run(target_count=count)
