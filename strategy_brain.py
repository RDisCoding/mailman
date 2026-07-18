"""
strategy_brain.py
-----------------
The LLM-powered decision engine for Cortogen's autonomous email agent.

What it does (every 3 days):
  1. Reads the last 3 days of campaign metrics + GA4 data
  2. Calls an LLM (OpenAI or Google Gemini) with a structured prompt
  3. Decides: next target audience, template improvements, website suggestions
  4. Saves a JSON report to reports/report_YYYY_MM_DD.json
  5. Queues the next lead generation job (writes to pending_lead_job.json)
  6. Sends you a plain-English report email

Run standalone:
  python strategy_brain.py

Or it's called automatically by autonomous_scheduler.py every 3 days.
"""

import os
import json
import time
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header

# Local modules
from metrics_logger import summarize_performance, get_last_n_campaigns
from ga4_collector import compute_ga4_delta

REPORTS_DIR       = os.path.join(os.path.dirname(__file__), "reports")
AGENT_CFG_FILE    = os.path.join(os.path.dirname(__file__), "agent_config.json")
CONFIG_FILE       = os.path.join(os.path.dirname(__file__), "config.json")
PENDING_JOB_FILE  = os.path.join(os.path.dirname(__file__), "pending_lead_job.json")

# ── Industry benchmarks ───────────────────────────────────────────────────────

COLD_EMAIL_BENCHMARKS = {
    "average_open_rate": 0.21,    # 21% industry average
    "good_open_rate":    0.30,    # 30% = strong
    "poor_open_rate":    0.10,    # <10% = likely in spam
    "reply_rate_avg":    0.02,    # 2% typical cold email reply rate
}

# ── Available target profiles ─────────────────────────────────────────────────

AVAILABLE_TARGETS = [
    {
        "id": "ai_power_users",
        "label": "AI Power Users (OpenAI/Anthropic/LangChain builders)",
        "scraper": "scrapers/buyer_intent_scraper.py",
        "rationale": "People who build with LLM APIs daily feel the context loss pain most acutely. Highest conversion probability."
    },
    {
        "id": "usa_indie_hackers",
        "label": "US Indie Hackers & Solopreneurs",
        "scraper": "scrapers/buyer_intent_scraper.py",
        "rationale": "High autonomy to try new tools, early adopters, English-first"
    },
    {
        "id": "eu_developers",
        "label": "EU Developers (UK, Germany, Netherlands)",
        "scraper": "scrapers/buyer_intent_scraper.py",
        "rationale": "Large dev population, tech-forward, good English fluency"
    },
    {
        "id": "corporate_ai_teams",
        "label": "Corporate AI/ML Researchers",
        "scraper": "corporate_ai_generator.py",
        "rationale": "High authority, but cold email hard; use only with warm template"
    },
    {
        "id": "india_startup_founders",
        "label": "Indian Startup Founders & CTOs",
        "scraper": "scrapers/buyer_intent_scraper.py",
        "rationale": "Decision-makers, not just developers. Higher intent than dev audience."
    },
]

# ── Config loading ─────────────────────────────────────────────────────────────

def load_config():
    with open(CONFIG_FILE, "r") as f:
        return json.load(f)

def load_agent_config() -> dict:
    if os.path.exists(AGENT_CFG_FILE):
        with open(AGENT_CFG_FILE, "r") as f:
            return json.load(f)
    return {}

# ── LLM Call ──────────────────────────────────────────────────────────────────

def call_llm(prompt: str, provider: str = None) -> dict:
    """
    Calls LLM with structured prompt. Returns parsed JSON dict.
    Supports: 'openai' or 'gemini'. Reads provider from agent_config.json.
    """
    agent_cfg = load_agent_config()
    if not provider:
        provider = agent_cfg.get("llm_provider", "openai").lower()

    print(f"[Brain] Calling LLM provider: {provider}")

    if provider == "openai":
        return _call_openai(prompt, agent_cfg)
    elif provider in ("gemini", "google"):
        return _call_gemini(prompt, agent_cfg)
    else:
        print(f"[Brain] Unknown provider '{provider}'. Falling back to mock.")
        return _mock_llm_response()


def _call_openai(prompt: str, cfg: dict) -> dict:
    try:
        import openai
        api_key = cfg.get("openai_api_key") or os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            print("[Brain] OpenAI API key not set. Using mock response.")
            return _mock_llm_response()

        client = openai.OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model=cfg.get("openai_model", "gpt-4o-mini"),
            messages=[
                {"role": "system", "content": "You are a growth strategy advisor for a developer tool called Cortogen. Respond ONLY with valid JSON."},
                {"role": "user",   "content": prompt}
            ],
            temperature=0.7,
            max_tokens=2000,
            response_format={"type": "json_object"}
        )
        raw = response.choices[0].message.content
        return json.loads(raw)
    except Exception as e:
        print(f"[Brain] OpenAI call failed: {e}")
        return _mock_llm_response()


def _call_gemini(prompt: str, cfg: dict) -> dict:
    try:
        import google.generativeai as genai
        api_key = cfg.get("gemini_api_key") or os.environ.get("GEMINI_API_KEY", "")
        if not api_key:
            print("[Brain] Gemini API key not set. Using mock response.")
            return _mock_llm_response()

        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(
            cfg.get("gemini_model", "gemini-1.5-flash"),
            generation_config={"response_mime_type": "application/json"}
        )
        response = model.generate_content(prompt)
        return json.loads(response.text)
    except Exception as e:
        print(f"[Brain] Gemini call failed: {e}")
        return _mock_llm_response()


def _mock_llm_response() -> dict:
    """Fallback when LLM is not configured — provides a sensible default."""
    return {
        "next_target_id": "usa_indie_hackers",
        "next_target_label": "US Indie Hackers & Solopreneurs",
        "next_target_rationale": "Indian developer outreach showed <10% open rate, suggesting low product-market fit with that segment. US indie hackers are early adopters who actively seek productivity tools for AI workflows.",
        "email_template_suggestions": [
            "Make the subject line more specific: instead of 'How much time do you spend repeating yourself to ChatGPT?' try 'I built a fix for ChatGPT's goldfish memory'",
            "Add a concrete time-saving stat in the opening line (e.g., 'saves the average dev 20 minutes/day')",
            "Shorten the email — the current template is too long for a cold email. Aim for 3 short paragraphs max.",
            "Add social proof: number of users, a quote, or a Product Hunt badge"
        ],
        "website_suggestions": [
            "Add a clear 'How it Works' section with 3 bullet points visible above the fold",
            "Show a before/after demo screenshot comparing a conversation with vs without Cortogen",
            "Add a social proof counter (e.g., '2,400+ developers trust Cortogen')",
            "The CTA button text 'Install Cortogen Free' is good — keep it, but make the button larger on mobile"
        ],
        "report": (
            "**3-Day Performance Summary**\n\n"
            "LLM is not yet configured (agent_config.json is missing llm_provider/api_key). "
            "This is a template report. Once you add your API key, the brain will generate "
            "real insights based on your actual campaign data.\n\n"
            "**Action items:**\n"
            "1. Add your OpenAI or Gemini API key to agent_config.json\n"
            "2. Run a new campaign to a different audience segment\n"
            "3. Verify your GA4 property ID is set in agent_config.json"
        ),
        "confidence": "low",
        "data_quality_note": "LLM not configured — this is a canned response."
    }

# ── Prompt Builder ────────────────────────────────────────────────────────────

def build_prompt(perf: dict, ga4: dict, history: list) -> str:
    targets_json = json.dumps(AVAILABLE_TARGETS, indent=2)
    benchmarks   = json.dumps(COLD_EMAIL_BENCHMARKS, indent=2)
    perf_json    = json.dumps(perf, indent=2)
    ga4_json     = json.dumps(ga4, indent=2)

    history_text = ""
    if history:
        history_text = "\n\nPrevious campaign summaries:\n"
        for h in history[-5:]:
            history_text += (
                f"- {h.get('started_at','')[:10]}: sent {h.get('total_sent',0)} to "
                f"{h.get('region','?')} using '{h.get('template_used','?')}' template. "
                f"Open rate: {h.get('open_rate',0):.1%}. "
                f"GA4 installs: {h.get('ga4_installs_delta',0)}\n"
            )

    prompt = f"""You are a growth strategy advisor for Cortogen — a Chrome extension that gives AI assistants (ChatGPT, Claude, Gemini) persistent memory across sessions.

TARGET PRODUCT: Cortogen is FREE. It solves the pain of having to repeat context to AI tools every new session. Install at cortogen.com.

COLD EMAIL INDUSTRY BENCHMARKS:
{benchmarks}

RECENT CAMPAIGN PERFORMANCE (last {perf.get('period_days',3)} days):
{perf_json}

GOOGLE ANALYTICS 4 DATA (last {ga4.get('period_days',3)} days):
{ga4_json}
{history_text}

AVAILABLE NEXT TARGETS:
{targets_json}

Based on this data, respond with a JSON object containing EXACTLY these keys:

{{
  "next_target_id": "<id from AVAILABLE TARGETS list>",
  "next_target_label": "<human readable label>",
  "next_target_rationale": "<1-2 sentence reason why this target is best RIGHT NOW based on the data>",
  "email_template_suggestions": [
    "<specific, actionable suggestion 1>",
    "<specific, actionable suggestion 2>",
    "<specific, actionable suggestion 3>"
  ],
  "website_suggestions": [
    "<specific cortogen.com improvement 1>",
    "<specific cortogen.com improvement 2>",
    "<specific cortogen.com improvement 3>"
  ],
  "report": "<3-5 paragraph plain English report for the founder. Include: what happened, what the data says, what to do next, and WHY. Be direct, no fluff.>",
  "confidence": "<high|medium|low based on data quantity>",
  "data_quality_note": "<any caveats about data quality>"
}}

RULES:
- Be specific. "Improve subject line" is not helpful. "Change subject from X to Y because..." is helpful.
- If open rate < 10%, assume spam folder is likely — suggest deliverability fixes.
- If GA4 installs are 0 and sends are >100, suggest the audience is wrong OR the UTM tracking is broken.
- Consider time zones: US audience should get emails at 9-11am EST.
- The founder's name is Rudra. Write the report addressed to him directly.
"""
    return prompt

# ── Report Delivery ───────────────────────────────────────────────────────────

def send_report_email(report_data: dict):
    """Send a formatted HTML report email to the notification address."""
    try:
        cfg = load_config()
        sender    = cfg.get("sender_email")
        password  = cfg.get("app_password")
        notify    = cfg.get("notification_email", "rudraydave@gmail.com")
        smtp_host = cfg.get("smtp_host", "smtp.sendgrid.net")
        smtp_port = cfg.get("smtp_port", 465)
        smtp_user = cfg.get("smtp_username", "apikey")

        if not sender or not password:
            print("[Brain] Email config missing. Skipping report email.")
            return

        subject = f"🧠 Cortogen AI Report — {datetime.now().strftime('%b %d, %Y')}"

        # Build HTML report
        suggestions_html = "".join(
            f"<li>{s}</li>" for s in report_data.get("email_template_suggestions", [])
        )
        website_html = "".join(
            f"<li>{s}</li>" for s in report_data.get("website_suggestions", [])
        )
        report_text = report_data.get("report", "No report generated.").replace("\n", "<br>")

        html_body = f"""
<!DOCTYPE html>
<html>
<head>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0f0f0f; color: #e0e0e0; margin: 0; padding: 0; }}
  .container {{ max-width: 640px; margin: 0 auto; padding: 32px 24px; }}
  .header {{ border-bottom: 1px solid rgba(251,133,0,0.4); padding-bottom: 20px; margin-bottom: 28px; }}
  .badge {{ display: inline-block; background: linear-gradient(135deg, #FFB703, #FB8500); color: #000; font-size: 11px; font-weight: 700; padding: 4px 10px; border-radius: 12px; letter-spacing: 1px; text-transform: uppercase; }}
  h1 {{ font-size: 24px; font-weight: 700; color: #fff; margin: 12px 0 4px; }}
  .meta {{ font-size: 13px; color: #666; }}
  .section {{ background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.07); border-radius: 10px; padding: 20px 24px; margin-bottom: 20px; }}
  .section h2 {{ font-size: 14px; font-weight: 700; color: #FB8500; letter-spacing: 1px; text-transform: uppercase; margin: 0 0 12px; }}
  .next-target {{ background: rgba(251,133,0,0.08); border: 1px solid rgba(251,133,0,0.3); border-radius: 10px; padding: 20px 24px; margin-bottom: 20px; }}
  .next-target .label {{ font-size: 18px; font-weight: 700; color: #FFB703; margin-bottom: 8px; }}
  ul {{ margin: 0; padding-left: 20px; line-height: 1.8; color: #c0c0c0; font-size: 14px; }}
  p {{ line-height: 1.7; color: #c0c0c0; font-size: 14px; margin: 0 0 10px; }}
  .confidence {{ display: inline-block; padding: 3px 10px; border-radius: 8px; font-size: 12px; font-weight: 600; }}
  .confidence.high {{ background: rgba(0,200,100,0.15); color: #00c864; }}
  .confidence.medium {{ background: rgba(255,183,3,0.15); color: #FFB703; }}
  .confidence.low {{ background: rgba(255,80,80,0.15); color: #ff5050; }}
  .footer {{ text-align: center; padding-top: 24px; border-top: 1px solid rgba(255,255,255,0.06); font-size: 12px; color: #444; }}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <div class="badge">🧠 AI Strategy Report</div>
    <h1>Cortogen Autonomous Agent</h1>
    <div class="meta">Generated {datetime.now().strftime('%A, %B %d, %Y at %H:%M')} &nbsp;·&nbsp;
      Confidence: <span class="confidence {report_data.get('confidence','low')}">{report_data.get('confidence','unknown').upper()}</span>
    </div>
  </div>

  <div class="next-target">
    <div class="label">📍 Next Target: {report_data.get('next_target_label', 'TBD')}</div>
    <p>{report_data.get('next_target_rationale', '')}</p>
  </div>

  <div class="section">
    <h2>📊 Performance Report</h2>
    <p>{report_text}</p>
  </div>

  <div class="section">
    <h2>✉️ Email Template Suggestions</h2>
    <ul>{suggestions_html}</ul>
  </div>

  <div class="section">
    <h2>🌐 Website Suggestions</h2>
    <ul>{website_html}</ul>
  </div>

  <div class="footer">
    <strong style="color:#FB8500">CORTOGEN</strong> Autonomous Agent · Giving AI a memory.<br>
    <span style="color:#333">Data note: {report_data.get('data_quality_note','')}</span>
  </div>
</div>
</body>
</html>"""

        msg = MIMEMultipart("alternative")
        msg["Subject"] = Header(subject, "utf-8")
        msg["From"]    = Header(f"Cortogen Brain <{sender}>", "utf-8")
        msg["To"]      = Header(notify, "utf-8")
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        if smtp_port == 587:
            with smtplib.SMTP(smtp_host, smtp_port) as srv:
                srv.starttls()
                srv.login(smtp_user, password)
                srv.sendmail(sender, [notify], msg.as_string())
        else:
            with smtplib.SMTP_SSL(smtp_host, smtp_port) as srv:
                srv.login(smtp_user, password)
                srv.sendmail(sender, [notify], msg.as_string())

        print(f"[Brain] Report email sent to {notify}")
    except Exception as e:
        print(f"[Brain] Failed to send report email: {e}")

# ── Lead Job Queue ────────────────────────────────────────────────────────────

def queue_lead_generation_job(target_id: str, target_label: str, scraper: str):
    """
    Writes pending_lead_job.json so the autonomous scheduler picks it up
    and runs the appropriate scraper during idle time.
    """
    job = {
        "target_id":    target_id,
        "target_label": target_label,
        "scraper":      scraper,
        "queued_at":    datetime.now().isoformat(),
        "status":       "pending"
    }
    with open(PENDING_JOB_FILE, "w") as f:
        json.dump(job, f, indent=2)
    print(f"[Brain] Lead job queued: {target_label} → {scraper}")

SCORE_CFG_FILE = os.path.join(os.path.dirname(__file__), "buyer_score_config.json")


def _load_scrape_summary() -> dict:
    """Read the summary from the last buyer-intent scrape run."""
    path = os.path.join(os.path.dirname(__file__), "metrics", "last_scrape_summary.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {}


def _load_current_score_config() -> dict:
    """Read current buyer score weights (or defaults)."""
    if os.path.exists(SCORE_CFG_FILE):
        with open(SCORE_CFG_FILE) as f:
            return json.load(f)
    return {
        "min_buyer_score": 40,
        "weights": {
            "uses_openai_api": 25, "uses_anthropic_api": 20,
            "uses_langchain": 15,  "uses_other_ai_lib": 10,
            "starred_ai_memory_tool": 20, "bio_mentions_ai": 15,
            "has_ai_topic_repo": 10, "active_last_3_months": 10,
            "has_personal_website": 10, "is_indie_or_freelance": 5,
            "many_public_repos": 5, "penalty_big_corp": -20,
            "penalty_no_repos": -10
        }
    }


def run_score_improvement_cycle(perf: dict, analysis: dict):
    """
    Uses the LLM to tune buyer scoring weights based on which signals
    correlated with actual conversions (open rates + GA4 installs).

    If open rate is low despite high buyer scores, it means the scores
    are measuring the wrong thing — the LLM can correct weights.
    """
    scrape_summary   = _load_scrape_summary()
    current_cfg      = _load_current_score_config()

    if not scrape_summary:
        print("[Brain] No scrape summary found. Skipping score improvement.")
        return

    avg_open_rate = perf.get("avg_open_rate", 0)
    avg_score     = scrape_summary.get("avg_buyer_score", 0)

    # Only refine if we have actual campaign data to learn from
    if not perf.get("data_available") or perf.get("total_sent", 0) < 20:
        print("[Brain] Not enough campaign data yet to improve scoring. Skipping.")
        return

    score_prompt = f"""You are improving a buyer-intent scoring system for Cortogen email outreach.

Current scoring weights (0-100 scale):
{json.dumps(current_cfg['weights'], indent=2)}

Current min_buyer_score threshold: {current_cfg['min_buyer_score']}

Last scrape results:
- Average buyer score of leads scraped: {avg_score}/100
- Total leads scraped: {scrape_summary.get('total_saved', 0)}

Campaign performance after emailing these leads:
- Emails sent: {perf.get('total_sent', 0)}
- Open rate: {avg_open_rate:.1%} (industry avg: 21%)
- GA4 installs attributed: {perf.get('total_sent', 0)}

Context: Cortogen is a Chrome extension for AI memory. Buyers are people who use
ChatGPT/Claude/Gemini daily and feel frustrated losing context between sessions.
The ideal buyer BUILDS with AI APIs (openai, anthropic, langchain).

Based on the gap between predicted buyer quality (avg_score={avg_score}) and
actual engagement (open_rate={avg_open_rate:.1%}), suggest improved weights.

Respond with ONLY this JSON structure:
{{
  "min_buyer_score": <integer 30-70>,
  "weights": {{
    "uses_openai_api": <int>,
    "uses_anthropic_api": <int>,
    "uses_langchain": <int>,
    "uses_other_ai_lib": <int>,
    "starred_ai_memory_tool": <int>,
    "bio_mentions_ai": <int>,
    "has_ai_topic_repo": <int>,
    "active_last_3_months": <int>,
    "has_personal_website": <int>,
    "is_indie_or_freelance": <int>,
    "many_public_repos": <int>,
    "penalty_big_corp": <negative int>,
    "penalty_no_repos": <negative int>
  }},
  "reasoning": "<1 sentence explaining the key change made>"
}}"""

    new_cfg = call_llm(score_prompt)

    if "weights" in new_cfg and "min_buyer_score" in new_cfg:
        new_cfg["updated_at"]    = datetime.now().isoformat()
        new_cfg["previous_open_rate"] = avg_open_rate
        new_cfg["previous_avg_score"] = avg_score
        with open(SCORE_CFG_FILE, "w") as f:
            json.dump(new_cfg, f, indent=2)
        print(f"[Brain] Buyer score config updated. New min={new_cfg['min_buyer_score']}. "
              f"Reasoning: {new_cfg.get('reasoning', 'N/A')}")
    else:
        print("[Brain] Score improvement LLM response invalid. Keeping current config.")


# ── Main Entry ─────────────────────────────────────────────────────────────────

def run_strategy_cycle():
    """Full 3-day strategy cycle."""
    print("\n" + "=" * 60)
    print("  Cortogen Strategy Brain -- Running Analysis")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # 1. Gather data
    perf    = summarize_performance(days=3)
    ga4     = compute_ga4_delta(days=3)
    history = get_last_n_campaigns(10)

    print(f"[Brain] Campaign perf: {perf['campaigns_run']} campaigns, "
          f"{perf['total_sent']} sent, {perf['avg_open_rate']:.1%} open rate")
    print(f"[Brain] GA4: {ga4['total_new_users']} new users, "
          f"{ga4['total_installs']} installs in last 3 days")

    # 2. Build prompt and call LLM for strategy
    prompt   = build_prompt(perf, ga4, history)
    analysis = call_llm(prompt)

    # 3. Save report JSON
    os.makedirs(REPORTS_DIR, exist_ok=True)
    report_filename = os.path.join(
        REPORTS_DIR,
        f"report_{datetime.now().strftime('%Y_%m_%d_%H%M')}.json"
    )
    full_report = {
        "generated_at": datetime.now().isoformat(),
        "input_perf":   perf,
        "input_ga4":    ga4,
        "llm_output":   analysis,
    }
    with open(report_filename, "w") as f:
        json.dump(full_report, f, indent=2)
    print(f"[Brain] Report saved: {report_filename}")

    # 4. Self-improve buyer scoring weights based on what converted
    run_score_improvement_cycle(perf, analysis)

    # 5. Queue next lead generation job
    target_id    = analysis.get("next_target_id", "ai_power_users")
    target_label = analysis.get("next_target_label", "AI Power Users")
    target_info  = next((t for t in AVAILABLE_TARGETS if t["id"] == target_id), None)
    if target_info and target_info.get("scraper"):
        queue_lead_generation_job(target_id, target_label, target_info["scraper"])
    else:
        print(f"[Brain] No scraper mapped for target '{target_id}'. Skipping job queue.")

    # 6. Send email report
    send_report_email(analysis)

    print("\n[Brain] Strategy cycle complete.")
    return analysis


if __name__ == "__main__":
    result = run_strategy_cycle()
    print("\n--- LLM Recommendation ---")
    print(f"Next target:  {result.get('next_target_label')}")
    print(f"Rationale:    {result.get('next_target_rationale')}")
    print(f"Confidence:   {result.get('confidence')}")
