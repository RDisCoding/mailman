# Cortogen Student Outreach Dashboard — Operator's Manual

Welcome to your **Cortogen Outreach Suite**! This suite consists of three integrated tools:
1. **Interactive Dashboard (`index.html` + `server.py`)**: View stats, custom-edit emails, predict email addresses, and manually compose drafts.
2. **Automated Background Scheduler (`scheduler.py`)**: A daemon script that runs in the background to automatically send emails daily using Gmail SMTP with staggered delays.
3. **GitHub Student Compiler (`student_generator.py`)**: A lead generation tool that queries GitHub's search API for student developers with public emails and builds your database instantly.

---

## 🚀 Running the Dashboard (Visual Monitoring)

The local dashboard allows you to monitor your campaign stats, customize drafts, and track progress.

1. **Start the local server:**
   ```powershell
   python server.py
   ```
2. **Open your browser to:**
   👉 **[http://localhost:8000](http://localhost:8000)**

*Note: Since the scheduler and compiler write directly to `researchers.json` on disk, the dashboard UI will automatically reflect newly scraped leads, list statuses, and sent/error counters live!*

---

## 💡 Automated Background Scheduler (`scheduler.py`)

If you want the campaign to run autonomously without manual clicking, you can schedule it as a daemon.

### 1. Configure SMTP Credentials
Open `config.json` in your editor and configure your settings:
```json
{
  "sender_email": "your_gmail_address@gmail.com",
  "app_password": "your_gmail_app_password",
  "daily_limit": 50,
  "min_delay_seconds": 60,
  "max_delay_seconds": 120,
  "notification_email": "your_gmail_address@gmail.com"
}
```
> [!IMPORTANT]
> **Gmail App Password Setup:**
> 1. Go to your Google Account Settings -> **Security**.
> 2. Ensure **2-Step Verification** is enabled.
> 3. Search for **App Passwords** or go to `https://myaccount.google.com/apppasswords`.
> 4. Create a new App Password (name it "Cortogen Outreach") and copy the 16-character code into `app_password` in `config.json`.

### 2. Run the Scheduler
* **Single Batch Mode** (Sends one day's quota and exits):
  ```powershell
  python scheduler.py
  ```
* **Daemon/Cron Mode** (Sends one day's quota, then sleeps for 24 hours, running continuously in the background):
  ```powershell
  python scheduler.py --daemon
  ```

### 3. Safety and Staggering
* The script reads `researchers.json`, finds targets marked `"not_contacted"`, and sends up to `daily_limit` emails.
* It inserts a random delay (e.g. 60–120 seconds) between each email to mimic manual writing and protect your domain reputation.
* After each successful send, it updates `researchers.json` to mark the contact as `"sent"`, ensuring zero double-send risks.
* Once the list is empty (0 pending targets left), the scheduler will automatically email a completion notification to your `notification_email` to alert you to load a new list.

---

## 🔍 GitHub Lead Generation Helper (`student_generator.py`)

You can generate targeted lists of student developers containing public university email addresses using the GitHub Compiler.

### 1. Run the Compiler (Free search, ~150 leads)
Run the script to query GitHub for students with public email addresses ending in top university domains (Stanford, CMU, MIT, Berkeley, Georgia Tech, Harvard, Cambridge, etc.):
```powershell
python student_generator.py --limit 10
```
This will fetch up to 10 users per university (approx. 150 contacts) and compile them directly into `researchers.json`.

### 2. Run the Compiler with Authenticated PAT (Up to 800+ leads)
To compile much larger lists without hitting GitHub's unauthenticated API rate limits:
1. Generate a free **Personal Access Token (classic)** on GitHub (Settings -> Developer Settings -> Personal Access Tokens -> Tokens classic). No scopes/permissions are required—just a public-read token.
2. Run the script with your token and a higher limit:
   ```powershell
   python student_generator.py --token YOUR_GITHUB_TOKEN --limit 50
   ```
This will fetch up to 50 developers per university domain (approx. 750 target leads) and save them to `researchers.json`.

### 3. Customizing the University List
To add or remove universities, open `student_generator.py` and modify the `DEFAULT_UNIVERSITIES` dictionary near the top of the file:
```python
DEFAULT_UNIVERSITIES = {
    "stanford.edu": "Stanford University",
    "mit.edu": "MIT",
    "gatech.edu": "Georgia Tech",
    # Add your own domains here...
}
```

---

## 📁 Repository Structure Reference

* `server.py`: The local dashboard web server.
* `index.html`: Interactive dashboard frontend.
* `researchers.json`: Central campaign database (reads/writes dynamically by UI, scheduler, and compiler).
* `config.json`: Private SMTP and email credentials.
* `scheduler.py`: Automated daily background sender.
* `student_generator.py`: Automated lead generation tool.
