# Mailman: User Outreach System

Mailman is an automated, self-contained system designed to scrape developer leads from GitHub and execute daily staggered email outreach campaigns. It features a modern glassmorphic web dashboard for manual drafts verification, stats tracking, and a background batch campaign dispatcher with live console log streaming and status email reports.

---

## Features

1. **Lead Scraping (`github_users.py`)**:
   * Page-by-page developer search queries rotating count sub-segments (e.g. `repos:5..10`) to bypass GitHub search limits.
   * Dynamic profile email resolution using the `/users/{username}` endpoint.
   * Automatic filtering of organizations and developers without public emails.
   * Incremental CSV outputs to safeguard data.
2. **Outreach Server (`server.py` & `index.html`)**:
   * Glassmorphism dark mode UI loading leads dynamically using query parameters (e.g., `?file=github_developers_india.csv`).
   * Staggered background thread SMTP dispatcher that sleeps for randomized increments (60-120 seconds) to avoid spam filters.
   * Progress modal with real-time stats updating, status messages, and logs.
   * Immediate campaign interruption/cancellation via a "Stop Campaign" button.
3. **Internal Summary Reports**:
   * Automatically emails a run summary (attempted, success, failed, and exact network/SMTP error messages) to the operator's personal email when a batch completes or is stopped.

---

## Project Structure

```
├── .gitignore               # Excludes secrets (config.json) and email lists (*.csv)
├── config.json              # Active SMTP credentials and delay timers (local only)
├── config.json.template     # Template for configuration
├── github_users.py          # Unified scraper & resolver script
├── index.html               # Responsive web interface
├── outreach_guide.md        # Reference template and custom subjects guide
├── scheduler.py             # CLI-based campaign runner alternative
├── server.py                # Python web backend server
└── README.md                # This documentation
```

---

## Getting Started

### 1. Requirements & Dependencies
Ensure you have Python 3.x installed. Install the `requests` module:
```bash
pip install requests
```

### 2. Configuration Setup
Create a `config.json` in the root of the project by copying `config.json.template`:
```json
{
  "sender_email": "your_outreach_gmail@gmail.com",
  "app_password": "xxxx xxxx xxxx xxxx", 
  "daily_limit": 50,
  "min_delay_seconds": 60,
  "max_delay_seconds": 120,
  "notification_email": "your_personal_email@gmail.com"
}
```

> [!IMPORTANT]
> **Google App Password**: Gmail requires a 16-character third-party App Password. Turn on 2-Step Verification in Google Account -> Security -> App Passwords and generate one named `Outreach`.

---

## Usage Guide

### Step 1: Scrape Developer Leads
Run the scraper to gather verified emails from GitHub.
```bash
# Example: Gather 1000 Indian developer profiles with public emails
python github_users.py --output github_developers_india.csv --location India --limit 1000

# Example: Gather 500 Spanish developer profiles with public emails
python github_users.py --output github_developers_spain.csv --location Spain --limit 500
```
*Note: Set your `GITHUB_TOKEN` as an environment variable to bypass GitHub search API rate limits.*

### Step 2: Run the Web Dashboard
Launch the Python web server:
```bash
python server.py
```
Open your browser and navigate to the dashboard with the corresponding query parameter:
* India Leads: `http://localhost:8000/?file=github_developers_india.csv`
* Spain Leads: `http://localhost:8000/?file=github_developers_spain.csv`

### Step 3: Run the Daily Campaign
1. Open the dashboard.
2. Click **Start Daily Batch** in the top right.
3. The progress modal will open, showing live console logs and status tracking.
4. When finished or stopped, you will receive a run summary report in your inbox.
5. Repeat daily! (The system automatically skips leads already marked as `sent` and retries ones that failed).

---

## Operating from Your Phone
Since the dashboard has a mobile-responsive layout, you can easily launch and monitor campaigns from your phone:

* **On the same Wi-Fi**: Go to your computer's local IP address on your phone's browser (e.g. `http://192.168.1.15:8000/?file=github_developers_india.csv`).
* **From anywhere (3G/4G/5G)**: Expose the local port on your computer using ngrok (`ngrok http 8000`) and access the generated secure URL on your phone's browser.
