import os
import re
import json
import time
import base64
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import requests

# Configuration from Environment Variables
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")
GITHUB_PAT = os.getenv("GITHUB_PAT", "")
GITHUB_SYNC_REPO = os.getenv("GITHUB_SYNC_REPO", "gitrepodevcoder/git-sync-hub")
GITHUB_USER = os.getenv("GITHUB_USER", "gitrepodevcoder")

TELEGRAM_API_BASE = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

# Lightweight HTTP Health Server for Render
class HealthServerHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain; charset=utf-8')
        self.end_headers()
        self.wfile.write(b"")

    def log_message(self, format, *args):
        return

def start_health_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthServerHandler)
    server.serve_forever()

def send_telegram_message(chat_id, text, reply_to_message_id=None):
    url = f"{TELEGRAM_API_BASE}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    if reply_to_message_id:
        payload["reply_to_message_id"] = reply_to_message_id
    for attempt in range(2):
        try:
            requests.post(url, json=payload, timeout=25)
            break
        except Exception as e:
            print(f"Error sending message: {e}")
            time.sleep(1)

def parse_github_url(text):
    # Regex to extract github owner and repo
    pattern = r'(?:https?://)?github\.com/([a-zA-Z0-9_\.-]+)/([a-zA-Z0-9_\.-]+)'
    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        owner = match.group(1).strip()
        repo = match.group(2).strip().rstrip(".git").rstrip("/").rstrip(".,;")
        canonical_url = f"https://github.com/{owner}/{repo}"
        return canonical_url, owner, repo
    return None, None, None

def get_repos_txt_from_github():
    url = f"https://api.github.com/repos/{GITHUB_SYNC_REPO}/contents/repos.txt"
    headers = {
        "Authorization": f"Bearer {GITHUB_PAT}",
        "Accept": "application/vnd.github.v3+json"
    }
    resp = requests.get(url, headers=headers, timeout=15)
    if resp.status_code == 200:
        data = resp.json()
        content = base64.b64decode(data["content"]).decode("utf-8")
        return content, data["sha"]
    return "", None

def append_repo_to_github(canonical_url):
    content, sha = get_repos_txt_from_github()
    lines = [line.strip() for line in content.splitlines()]

    # Check if already present
    for line in lines:
        if line.lower() == canonical_url.lower():
            return False, "Repository is already in your sync hub!"

    # Append new URL
    if content and not content.endswith("\n"):
        content += "\n"
    content += canonical_url + "\n"

    url = f"https://api.github.com/repos/{GITHUB_SYNC_REPO}/contents/repos.txt"
    headers = {
        "Authorization": f"Bearer {GITHUB_PAT}",
        "Accept": "application/vnd.github.v3+json"
    }
    payload = {
        "message": f"Add {canonical_url} via Telegram bot",
        "content": base64.b64encode(content.encode("utf-8")).decode("utf-8")
    }
    if sha:
        payload["sha"] = sha

    resp = requests.put(url, headers=headers, json=payload, timeout=20)
    if resp.status_code in [200, 201]:
        return True, "Added successfully"
    return False, f"GitHub API error ({resp.status_code}): {resp.text}"

def trigger_github_workflow():
    url = f"https://api.github.com/repos/{GITHUB_SYNC_REPO}/actions/workflows/sync-and-backup.yml/dispatches"
    headers = {
        "Authorization": f"Bearer {GITHUB_PAT}",
        "Accept": "application/vnd.github.v3+json"
    }
    payload = {"ref": "main"}
    resp = requests.post(url, headers=headers, json=payload, timeout=20)
    return resp.status_code == 204

def log_to_google_sheet(repo_name, original_link, private_mirror, drive_status):
    if not WEBHOOK_URL:
        return None
    try:
        payload = {
            "repo_name": repo_name,
            "original_link": original_link,
            "private_mirror": private_mirror,
            "drive_status": drive_status
        }
        resp = requests.post(WEBHOOK_URL, json=payload, timeout=20)
        return resp.json()
    except Exception as e:
        print(f"Error logging to Google Sheet: {e}")
        return None

def process_message(message):
    chat_id = message["chat"]["id"]
    text = message.get("text") or message.get("caption") or ""
    message_id = message["message_id"]

    clean_text = text.strip()

    if clean_text in ["/start", "/help"]:
        help_msg = (
            "👋 *Welcome to GitHub Repo Sync & Backup Bot!*\n\n"
            "Simply send me any GitHub repository link, and I will:\n"
            "1. Add it to `git-sync-hub`\n"
            "2. Trigger automatic sync to your private GitHub (`gitrepodevcoder`)\n"
            "3. Create versioned `.zip` archives on your Google Drive\n"
            "4. Log the repository into your dedicated Google Sheet!\n\n"
            "Commands:\n"
            "• Send any URL: `https://github.com/owner/repo`\n"
            "• `/list` - View all currently tracked repositories\n"
            "• `/sync` - Manually trigger sync & backup right now"
        )
        send_telegram_message(chat_id, help_msg, message_id)
        return

    if clean_text == "/list":
        content, _ = get_repos_txt_from_github()
        active_repos = [l for l in content.splitlines() if l.strip() and not l.strip().startswith("#")]
        if not active_repos:
            send_telegram_message(chat_id, "ℹ️ No repositories tracked yet. Send a GitHub link to start!", message_id)
        else:
            list_text = "📦 *Currently Tracked Repositories:*\n\n" + "\n".join([f"{i+1}. {r}" for i, r in enumerate(active_repos)])
            send_telegram_message(chat_id, list_text, message_id)
        return

    if clean_text == "/sync":
        send_telegram_message(chat_id, "⏳ *Triggering Git Sync & Google Drive Backup workflow...*", message_id)
        if trigger_github_workflow():
            send_telegram_message(chat_id, "✅ *GitHub Actions Workflow Triggered!*\n\nAll repositories are syncing to your private GitHub and backing up to Google Drive now.", message_id)
        else:
            send_telegram_message(chat_id, "❌ Failed to trigger workflow. Please check GitHub permissions.", message_id)
        return

    canonical_url, owner, repo = parse_github_url(clean_text)
    if not canonical_url:
        send_telegram_message(chat_id, "ℹ️ Please send a valid GitHub repository link!\n\n_Example:_\n`https://github.com/shadcn-ui/ui`", message_id)
        return

    send_telegram_message(chat_id, f"⏳ *Processing GitHub Repository: `{repo}`...*\nAdding to sync hub and queuing backup...", message_id)

    # 1. Append to repos.txt
    success, msg = append_repo_to_github(canonical_url)
    private_mirror = f"https://github.com/{GITHUB_USER}/{repo}"
    drive_folder = f"GitBackups/{repo}/"

    # 2. Trigger workflow
    wf_success = trigger_github_workflow()
    drive_status = f"Sync & Backup Triggered ({drive_folder})" if wf_success else "Added to repos.txt (Sync pending)"

    # 3. Log to Google Sheet
    sheet_res = log_to_google_sheet(repo, canonical_url, private_mirror, drive_status)

    # 4. Confirmation message
    if success:
        reply = "🚀 *Repository Successfully Added & Synced!*\n\n"
    else:
        reply = "ℹ️ *Repository Already Tracked!*\nTriggered fresh sync and updated sheet.\n\n"

    reply += f"📦 *Repo Name:* `{repo}`\n"
    reply += f"🌐 *Original:* {canonical_url}\n"
    reply += f"🔒 *Private Mirror:* {private_mirror}\n"
    reply += f"💾 *Google Drive:* `{drive_folder}`\n"
    if sheet_res and sheet_res.get("status") == "success":
        reply += f"\n📊 *Logged in your Google Sheet!*"
    else:
        reply += f"\n📊 *Sheet:* Connected"

    send_telegram_message(chat_id, reply, message_id)

def main():
    print("GitHub Sync Bot is running...")
    threading.Thread(target=start_health_server, daemon=True).start()
    print("Health server running on port " + os.getenv("PORT", "8080"))

    offset = None
    while True:
        try:
            url = f"{TELEGRAM_API_BASE}/getUpdates"
            params = {"timeout": 30}
            if offset:
                params["offset"] = offset

            resp = requests.get(url, params=params, timeout=40)
            if resp.status_code == 200:
                data = resp.json()
                for update in data.get("result", []):
                    offset = update["update_id"] + 1
                    msg = update.get("message") or update.get("channel_post") or update.get("edited_message")
                    if msg:
                        process_message(msg)
        except Exception as e:
            print(f"Polling error: {e}")
            time.sleep(3)

if __name__ == "__main__":
    main()
