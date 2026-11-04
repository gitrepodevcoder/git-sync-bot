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
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID", "-1004364399708")

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

def reset_repos_txt():
    current_content, sha = get_repos_txt_content()
    clean_content = "# Add your GitHub repository URLs here (one per line)\n"
    url = f"https://api.github.com/repos/{GITHUB_SYNC_REPO}/contents/repos.txt"
    headers = {
        "Authorization": f"Bearer {GITHUB_PAT}",
        "Accept": "application/vnd.github.v3+json"
    }
    payload = {
        "message": "Reset repos.txt via /clean command",
        "content": base64.b64encode(clean_content.encode("utf-8")).decode("ascii")
    }
    if sha:
        payload["sha"] = sha
    r = requests.put(url, headers=headers, json=payload)
    return r.status_code in [200, 201]

def trigger_github_workflow(workflow_name="sync-and-backup.yml"):
    if not GITHUB_PAT or not GITHUB_SYNC_REPO:
        return False
    url = f"https://api.github.com/repos/{GITHUB_SYNC_REPO}/actions/workflows/{workflow_name}/dispatches"
    headers = {
        "Authorization": f"Bearer {GITHUB_PAT}",
        "Accept": "application/vnd.github.v3+json"
    }
    r = requests.post(url, headers=headers, json={"ref": "main"})
    return r.status_code == 204

def log_to_google_sheet(repo_name, original_link, private_mirror, drive_status, action=None):
    if not WEBHOOK_URL:
        return None
    try:
        payload = {
            "repo_name": repo_name,
            "original_link": original_link,
            "private_mirror": private_mirror,
            "drive_status": drive_status
        }
        if action:
            payload["action"] = action
        r = requests.post(WEBHOOK_URL, json=payload, timeout=20)
        return r.json()
    except Exception as e:
        print(f"Error logging to Google Sheet: {e}")
        return None

def clean_telegram_channel():
    try:
        marker_res = requests.post(
            f"{TELEGRAM_API_BASE}/sendMessage",
            json={"chat_id": TELEGRAM_CHANNEL_ID, "text": "🧹 *Channel Resetting...*", "parse_mode": "Markdown"},
            timeout=10
        )
        if marker_res.status_code == 200:
            max_id = marker_res.json()["result"]["message_id"]
            for mid in range(max_id, max(1, max_id - 60), -1):
                try:
                    requests.post(
                        f"{TELEGRAM_API_BASE}/deleteMessage",
                        json={"chat_id": TELEGRAM_CHANNEL_ID, "message_id": mid},
                        timeout=2
                    )
                except Exception:
                    pass
        requests.post(
            f"{TELEGRAM_API_BASE}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHANNEL_ID,
                "text": "✨ *Channel Cleaned & Ready!*\nAll previous backup archives have been cleared. Ready for fresh repository backups.",
                "parse_mode": "Markdown"
            },
            timeout=10
        )
        return True
    except Exception as e:
        print(f"Error cleaning channel: {e}")
        return False

def handle_clean_command(chat_id, message_id):
    send_telegram_message(
        chat_id,
        "🧹 *Initiating Full Cleanup...*\n\n"
        "1. 💾 Google Drive: Purging `GitBackups/` via Cloud Action...\n"
        "2. 📁 Telegram Channel: Deleting backup files...\n"
        "3. 📋 repos.txt: Resetting queue...\n"
        "4. 📊 Google Sheet: Sending clear signal...",
        message_id
    )

    # 1. Get tracked repos before reset
    content, _ = get_repos_txt_content()
    tracked_repos = []
    for line in content.splitlines():
        if line.strip() and not line.strip().startswith("#"):
            _, r_name, _ = parse_github_url(line)
            if r_name:
                tracked_repos.append(r_name)

    # 2. Trigger Google Drive purge workflow
    drive_clean = trigger_github_workflow("clean-drive.yml")

    # 3. Clean Telegram channel
    tg_clean = clean_telegram_channel()

    # 4. Reset repos.txt
    repo_reset = reset_repos_txt()

    # 5. Clean Google Sheet
    sheet_clean = log_to_google_sheet("", "", "", "", action="clean_all")

    # 6. Attempt deleting mirrored GitHub repos
    deleted_repos = []
    failed_repos = []
    headers = {"Authorization": f"Bearer {GITHUB_PAT}", "Accept": "application/vnd.github.v3+json"}
    for r_name in tracked_repos:
        del_r = requests.delete(f"https://api.github.com/repos/{GITHUB_USER}/{r_name}", headers=headers)
        if del_r.status_code == 204:
            deleted_repos.append(r_name)
        else:
            failed_repos.append(r_name)

    # Summary
    reply = "✅ *Cleanup Completed Successfully!*\n\n"
    reply += f"💾 *Google Drive:* `GitBackups/` purged\n"
    reply += f"📁 *Telegram Channel:* Documents cleared & channel refreshed\n"
    reply += f"📋 *repos.txt:* Reset to clean state (0 queued)\n"
    reply += f"📊 *Google Sheet:* Reset signal sent\n"

    if deleted_repos:
        reply += f"🔒 *GitHub Mirrored Repos Deleted:* {', '.join(deleted_repos)}\n"
    if failed_repos:
        reply += (
            f"\nℹ️ *Note on GitHub Repos ({', '.join(failed_repos)}):*\n"
            f"GitHub PAT lacks `delete_repo` permission. Aap repo Settings ➡️ Danger Zone se 1-click delete kar sakte hain, ya PAT me `delete_repo` scope on kar sakte hain."
        )

    send_telegram_message(chat_id, reply, message_id)

def process_message(message):
    chat_id = message["chat"]["id"]
    text = message.get("text") or message.get("caption") or ""
    message_id = message["message_id"]

    clean_text = text.strip().lower()
    if clean_text in ["/clean", "/reset", "clean", "reset"]:
        handle_clean_command(chat_id, message_id)
        return

    if clean_text.startswith("/start"):
        welcome_msg = (
            "👋 *Welcome to GitHub Repo Sync & Backup Bot!*\n\n"
            "Send me any GitHub repository link:\n"
            "• `https://github.com/expressjs/express`\n"
            "• `https://github.com/torvalds/linux`\n\n"
            "I will automatically:\n"
            "1. 🔒 Mirror the code to your private GitHub account.\n"
            "2. 💾 Archive versioned `.zip` to your Google Drive.\n"
            "3. 📁 Send `.zip` document directly to your Telegram Channel (`Git Repo Backup channel`).\n"
            "4. 📊 Log details into your Google Sheet!\n\n"
            "🧹 *Commands:*\n"
            "• `/clean` - Purge Google Drive, clear channel messages, reset Sheet and queue."
        )
        send_telegram_message(chat_id, welcome_msg, message_id)
        return

    owner, repo, canonical_url = parse_github_url(text)
    if not owner or not repo:
        send_telegram_message(chat_id, "ℹ️ Please send a valid GitHub URL!\n_Example:_ `https://github.com/owner/repository`\n\nOr use `/clean` to reset all backups.", message_id)
        return

    # Check for duplicate entry BEFORE touching Sheet or triggering Workflow
    current_content, _ = get_repos_txt_content()
    tracked_lines = [l.strip() for l in current_content.splitlines() if l.strip() and not l.strip().startswith("#")]
    
    is_duplicate = False
    for line in tracked_lines:
        _, ex_repo, ex_canon = parse_github_url(line)
        if (ex_repo and ex_repo.lower() == repo.lower()) or (ex_canon and ex_canon.lower() == canonical_url.lower()):
            is_duplicate = True
            break

    private_mirror = f"https://github.com/{GITHUB_USER}/{repo}"
    drive_folder = f"GitBackups/{repo}/"

    if is_duplicate:
        warning_msg = (
            f"⚠️ *Repository Already Added & Tracked!*\n\n"
            f"Yeh repository pehle se backup queue me maujood hai:\n\n"
            f"📦 *Repo Name:* `{repo}`\n"
            f"🌐 *Original:* {canonical_url}\n"
            f"🔒 *Private Mirror:* {private_mirror}\n"
            f"💾 *Google Drive:* `{drive_folder}`\n"
            f"📁 *Telegram Channel:* `Git Repo Backup channel`\n\n"
            f"ℹ️ _Duplicate entry Sheet me add nahi ki gayi hai._"
        )
        send_telegram_message(chat_id, warning_msg, message_id)
        return

    send_telegram_message(chat_id, f"⏳ *Processing `{repo}`...*\nAdding to sync queue and triggering cloud backup...", message_id)

    # 1. Append to repos.txt
    success, msg = append_repo_to_github(canonical_url)

    # 2. Trigger workflow
    wf_success = trigger_github_workflow("sync-and-backup.yml")
    drive_status = f"Sync & Backup Triggered ({drive_folder})" if wf_success else "Added to repos.txt (Sync pending)"

    # 3. Log to Google Sheet (ONLY for new repo)
    sheet_res = log_to_google_sheet(repo, canonical_url, private_mirror, drive_status)

    # 4. Confirmation message
    reply = (
        f"🚀 *Repository Successfully Added & Synced!*\n\n"
        f"📦 *Repo Name:* `{repo}`\n"
        f"🌐 *Original:* {canonical_url}\n"
        f"🔒 *Private Mirror:* {private_mirror}\n"
        f"💾 *Google Drive:* `{drive_folder}`\n"
        f"📁 *Telegram Channel:* `Git Repo Backup channel`\n"
    )
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
