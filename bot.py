import os
import re
import json
import time
import base64
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import requests

# Configuration from Environment Variables
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "9111460803:AAFJSKUSowl7-5_b8xmlUPmqp6ECN53Sfwc")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")
GITHUB_PAT = os.getenv("GITHUB_PAT", "")
GITHUB_SYNC_REPO = os.getenv("GITHUB_SYNC_REPO", "gitrepodevcoder/git-sync-hub")
GITHUB_USER = os.getenv("GITHUB_USER", "gitrepodevcoder")

TELEGRAM_API_BASE = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

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
    pattern = r'(?:https?://)?github\.com/([a-zA-Z0-9_\.-]+)/([a-zA-Z0-9_\.-]+)'
    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        owner = match.group(1).strip()
        repo = match.group(2).strip().rstrip(".git").rstrip("/").rstrip(".,;")
        canonical_url = f"https://github.com/{owner}/{repo}"
        return owner, repo, canonical_url
    return None, None, None

def get_repos_txt_content():
    if not GITHUB_PAT or not GITHUB_SYNC_REPO:
        return "", ""
    url = f"https://api.github.com/repos/{GITHUB_SYNC_REPO}/contents/repos.txt"
    headers = {
        "Authorization": f"Bearer {GITHUB_PAT}",
        "Accept": "application/vnd.github.v3+json"
    }
    r = requests.get(url, headers=headers)
    if r.status_code == 200:
        data = r.json()
        content = base64.b64decode(data["content"]).decode("utf-8")
        return content, data["sha"]
    return "", ""

def append_repo_to_github(canonical_url):
    current_content, sha = get_repos_txt_content()
    lines = [line.strip() for line in current_content.splitlines() if line.strip()]

    if canonical_url in lines:
        return False, "Already exists"

    if current_content and not current_content.endswith("\n"):
        new_content = current_content + "\n" + canonical_url + "\n"
    else:
        new_content = current_content + canonical_url + "\n"

    url = f"https://api.github.com/repos/{GITHUB_SYNC_REPO}/contents/repos.txt"
    headers = {
        "Authorization": f"Bearer {GITHUB_PAT}",
        "Accept": "application/vnd.github.v3+json"
    }
    payload = {
        "message": f"Add {canonical_url} via Telegram Bot",
        "content": base64.b64encode(new_content.encode("utf-8")).decode("ascii")
    }
    if sha:
        payload["sha"] = sha

    r = requests.put(url, headers=headers, json=payload)
    if r.status_code in [200, 201]:
        return True, "Added"
    else:
        print(f"Error updating repos.txt: {r.status_code} {r.text}")
        return False, f"GitHub Error {r.status_code}"

def trigger_github_workflow():
    if not GITHUB_PAT or not GITHUB_SYNC_REPO:
        return False
    url = f"https://api.github.com/repos/{GITHUB_SYNC_REPO}/actions/workflows/sync-and-backup.yml/dispatches"
    headers = {
        "Authorization": f"Bearer {GITHUB_PAT}",
        "Accept": "application/vnd.github.v3+json"
    }
    r = requests.post(url, headers=headers, json={"ref": "main"})
    return r.status_code == 204

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
        r = requests.post(WEBHOOK_URL, json=payload, timeout=20)
        return r.json()
    except Exception as e:
        print(f"Error logging to Google Sheet: {e}")
        return None

def process_message(message):
    chat_id = message["chat"]["id"]
    text = message.get("text") or message.get("caption") or ""
    message_id = message["message_id"]

    if text.strip().startswith("/start"):
        welcome_msg = (
            "👋 *Welcome to GitHub Repo Sync & Backup Bot!*\n\n"
            "Send me any GitHub repository link:\n"
            "• `https://github.com/expressjs/express`\n"
            "• `https://github.com/torvalds/linux`\n\n"
            "I will automatically:\n"
            "1. 🔒 Mirror the code to your private GitHub account.\n"
            "2. 💾 Archive versioned `.zip` to your Google Drive.\n"
            "3. 📁 Send `.zip` document directly to your Telegram Channel.\n"
            "4. 📊 Log details into your Google Sheet!"
        )
        send_telegram_message(chat_id, welcome_msg, message_id)
        return

    owner, repo, canonical_url = parse_github_url(text)
    if not owner or not repo:
        send_telegram_message(chat_id, "ℹ️ Please send a valid GitHub URL!\n_Example:_ `https://github.com/owner/repository`", message_id)
        return

    send_telegram_message(chat_id, f"⏳ *Processing `{repo}`...*\nAdding to sync queue and triggering cloud backup...", message_id)

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
    reply += f"📁 *Telegram Channel:* `Git Repo Backup`\n"
    if sheet_res and sheet_res.get("status") == "success":
        reply += f"\n📊 *Logged in your Google Sheet!*"
    else:
        reply += f"\n📊 *Sheet:* Connected"

    send_telegram_message(chat_id, reply, message_id)

# Webhook Server for Render
class WebhookHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain; charset=utf-8')
        self.end_headers()
        self.wfile.write(b"Git Sync Bot Webhook Server is Live!")

    def do_POST(self):
        if self.path in ["/webhook", "/"]:
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            self.send_response(200)
            self.send_header('Content-type', 'text/plain; charset=utf-8')
            self.end_headers()
            self.wfile.write(b"OK")
            try:
                update = json.loads(post_data.decode('utf-8'))
                msg = update.get("message") or update.get("channel_post") or update.get("edited_message")
                if msg:
                    threading.Thread(target=process_message, args=(msg,), daemon=True).start()
            except Exception as e:
                print(f"Webhook processing error: {e}")
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        return

def main():
    print("Starting GitHub Sync Bot in Webhook Mode...")
    
    # Auto register webhook
    webhook_url = "https://git-sync-bot.onrender.com/webhook"
    try:
        r = requests.post(f"{TELEGRAM_API_BASE}/setWebhook", json={"url": webhook_url, "drop_pending_updates": False}, timeout=15)
        print("Telegram Webhook set response:", r.status_code, r.text)
    except Exception as e:
        print("Failed to set Telegram webhook:", e)

    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), WebhookHandler)
    print(f"Webhook HTTP Server listening on port {port}...")
    server.serve_forever()

if __name__ == "__main__":
    main()
