# Git Sync Bot (`@gitreposyncbot`)

Telegram Bot that receives GitHub repository links and automates full multi-repo backup and synchronization.

## Features
- **Telegram Bot Interface**: Send any GitHub repository link (e.g. `https://github.com/shadcn-ui/ui`).
- **Auto-Sync to Private GitHub**: Mirrors upstream repository into private mirror under your GitHub account (`gitrepodevcoder`).
- **Cloud Backup to Google Drive**: Automatically creates versioned `.zip` archives of the repo on Google Drive (`GitBackups/{repo}/`).
- **Google Sheets Tracker**: Logs every added repo with name, original link, private mirror, and status into a dedicated Google Sheet.
- **On-Demand & Daily Sync**: Triggers GitHub Actions workflow instantly on new repos and runs daily at midnight UTC.
- **Deleted Repo Alert**: Detects if upstream repository was deleted or made private, and alerts you via GitHub Issues/Email while keeping your backups safe.

## Cloud Deployment
Hosted on Render as a Docker service with zero local container overhead.
