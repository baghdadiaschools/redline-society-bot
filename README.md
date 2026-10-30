# Redline Society bot

An always-on Discord worker for one server, built with Python and discord.py. R-coins are virtual community points: no real-money purchases, cash-out, wagering, or rigged casino features. A free practice race is included.

## What is implemented

- One R-coin for an eligible member message, with a persistent 30-second per-member cooldown. Bot, webhook, system and other-server messages are ignored.
- `/daily`: 100 R-coins every rolling 24 hours; restarting cannot bypass the cooldown.
- Owner-only balance set, add/subtract, reset, and bulk changes. Administrator/role permissions do not grant these controls; only `OWNER_ID` does.
- Owner-created role shop and file/video packages; member-created marketplace packages restricted to the owner's chosen channel. New listings post a public description card with a persistent Buy button in that channel.
- Atomic purchases: buyer debit, seller credit (marketplace only), ledger entry and permanent purchase entitlement commit together. Repeat buys cannot double-charge. Official shop purchases remove coins from circulation.
- Private file delivery, persistent inventory, free redelivery, withdrawn listings preserving previous purchases, listing pagination and leaderboard.
- SQL migrations, exact dependency locks, Docker worker, persistent volumes, restart policy, signal handling, structured event logs, health checks, backups, restore verification and CI.

The marketplace pays sellers **R-coins**, not real money. Each listing has one attachment; upload a ZIP for multiple files or upload a video directly. Uploaded files are never executed or unpacked by the bot. Distribution rights and moderation remain the server owner's responsibility. There is no antivirus scanner or DRM: a purchaser can copy a downloaded file or its Discord attachment URL.

## First-time setup: Discord

1. Open <https://discord.com/developers/applications> and select **New Application**. Name it **Redline Society bot**.
2. Open **Bot**. Create/reset the token as needed. Save it privately; never commit it or paste it into a message. If exposed, reset it immediately in this portal.
3. This bot uses slash commands and message events without reading message text. **Message Content** and **Server Members** privileged intents are not required. It can reward messages in channels it can see.
4. Under **Installation** or **OAuth2 > URL Generator**, select scopes `bot` and `applications.commands`. Request **View Channels**, **Send Messages**, **Embed Links**, **Attach Files**, and **Manage Roles**. Invite it to your server. Do not give it Administrator.
5. In Discord **Server Settings > Roles**, move the bot's role above any cosmetic roles you want to sell. Selling roles that have moderation/administration permissions is rejected.
6. In Discord **User Settings > Advanced**, enable **Developer Mode**. Right-click your server and choose **Copy Server ID** for `GUILD_ID`. Right-click your own user and choose **Copy User ID** for `OWNER_ID`.
7. Fill those values in a private `.env` file locally or your hosting service's secret/environment settings. Do not put the token in GitHub Actions: CI does not need it.

## Run locally on Windows (beginner steps)

1. Install Python 3.13 or 3.14 from <https://www.python.org/downloads/> and select **Add Python to PATH**.
2. Extract the project ZIP. Open its `redline-society-bot` folder in Visual Studio Code.
3. In VS Code choose **Terminal > New Terminal**. Check that the terminal is in the folder containing `README.md` and `requirements.lock`.
4. Run each command separately in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.lock
Copy-Item .env.example .env
notepad .env
```

5. Fill `DISCORD_TOKEN`, `GUILD_ID`, and `OWNER_ID`, then save and close Notepad. Keep the other defaults for local use. `.env` supports simple `KEY=value` lines and optional matching quotes; do not add inline comments to values.
6. Build and start:

```powershell
.\.venv\Scripts\python scripts/build.py
.\.venv\Scripts\python dist/redline.pyz
```

7. Wait for the log **Redline Society bot connected**. In your server try `/help`, `/daily`, and `/balance`. Commands are registered for `GUILD_ID` on startup. If they don't appear, confirm the invite includes `applications.commands`, then restart Discord.
8. Press **Ctrl+C** to stop gracefully. Your computer must stay on while running locally. Hosting it as described below avoids depending on your computer.

## Commands

| Command | Purpose |
| --- | --- |
| `/balance [member]` | Own or another member's balance |
| `/daily` | 100 coins every 24 hours |
| `/leaderboard` | Top ten balances |
| `/shop [page]` | Official role/package catalog |
| `/market [page]` | Member catalog, only in configured market channel |
| `/buy item_id` | Purchase and deliver an item; repeat calls never charge again |
| `/inventory [page]` | Your permanent purchases |
| `/download item_id` | Retry/retrieve a purchased file or role free of charge |
| `/sell title price file [description]` | Post a public package card with a Buy button in the selected market channel |
| `/remove item_id` | Seller withdraws own market item; owner can withdraw any item |
| `/listing_edit item_id [price] [description]` | Owner only: change any active listing's price/description and refresh its card |
| `/listing_post item_id` | Owner only: publish an older/unposted listing in the selected channel |
| `/race` | Free practice lap, no stakes or rewards |
| `/coins member mode amount` | Owner only: `set`, `add` (negative subtracts), or `reset` |
| `/coins_all mode confirmation amount` | Owner only; enter `CONFIRM ALL` exactly |
| `/market_channel channel` | Owner only: select marketplace channel |
| `/role_add role price [description]` | Owner only: list a cosmetic role and post its card when a channel is selected |
| `/pack_add title price file [description]` | Owner only: upload official package and post its card when a channel is selected |
| `/help` | Quick guide |

Bulk balance operations affect **existing accounts**, not every Discord member who has never interacted with the bot. New accounts start at zero. Balance resets preserve daily/message cooldowns, purchases, listings, and files. Official listings are immutable: withdraw and create a new listing to change a price/file. Previous buyers retain their old purchase. Owner balance changes are recorded in the `ledger` table with the actor's ID.

Command responses are private; listing cards are public in the channel selected by `/market_channel`. Select that channel before adding listings. A member's `/sell` posts automatically; official listings also post there when the channel is configured. Older listings can be published with `/listing_post`. The Buy button delivers privately and uses the same atomic purchase logic as `/buy`. Cards retain working buttons across bot restarts while the database and file storage survive; a withdrawn card has its button removed. The owner can edit any active listing, including a member listing, or remove any listing. Slash attachment uploads are saved to persistent storage immediately, so the original Discord upload URL expiring does not remove the package.

## GitHub: create the private repository and upload

The project repository is [baghdadiaschools/redline-society-bot](https://github.com/baghdadiaschools/redline-society-bot). The following steps also explain how to publish your own copy. Hosting setup and secret configuration are separate from publishing source code.

### Easiest route: GitHub Desktop

1. Install GitHub Desktop from <https://desktop.github.com/> and sign into your GitHub account.
2. Choose **File > New repository**. Name it `redline-society-bot`; choose a parent folder such as Documents. Do not initialize extra ignore/license templates.
3. Copy the **contents** of the extracted project folder into this new repository folder. `README.md`, `Dockerfile`, `compose.yaml`, `src`, `tests`, `.github`, and both lockfiles must be at the repository root, not inside a second nested folder. Include `.env.example`, `.gitignore`, and `.dockerignore`.
4. Before committing, inspect **Changes**. It must not contain `.env`, data folders, a database, backups, uploaded materials, or a bot token. This delivered ZIP has none of those private contents.
5. Enter **Initial Redline Society bot** as the commit summary, then **Commit to main**.
6. Click **Publish repository** and **keep “Keep this code private” checked**. Confirm the repository name, then publish.
7. Open it on GitHub. Verify it says **Private** and open the **Actions** tab. The workflow type-checks, tests and builds without production secrets. Do not deploy until checks pass.

### Git terminal alternative

Create a repository at <https://github.com/new>, name it `redline-society-bot`, choose **Private**, and leave README/gitignore/license initialization unchecked. In the extracted project folder run:

```text
git init -b main
git add .
git status --short
git diff --cached --stat
git commit -m "Initial Redline Society bot"
git remote add origin https://github.com/YOUR_USERNAME/redline-society-bot.git
git push -u origin main
```

Replace `YOUR_USERNAME` with your GitHub username. Review staged files before `git commit`. Authenticate through Git's browser/credential-manager flow; never embed a token in the remote URL. If Git asks for your name/email, set the identity you use for commits before retrying the commit.

## Hosting requirements

**Run this as an always-on background worker, not a static website.** GitHub Pages and static website hosting cannot keep its Discord Gateway connection alive. Services that sleep interrupt commands and message rewards. Messages missed during downtime are not replayed for rewards. You do not need a domain, public HTTP port, web server or API key other than the Discord bot token.

Use **one worker replica** with persistent local SSD storage. SQLite and the process lock prevent duplicate workers sharing the same disk, but separate disks would create separate economies. Do not horizontally scale this version or use a shared network filesystem. A PostgreSQL/object-storage redesign is needed for multiple replicas.

Required outbound connectivity: Discord HTTPS and Gateway WebSocket on port 443, plus Python package downloads during builds. Starting at 512 MB–1 GB RAM is reasonable; monitor actual use. Budget space for the live database, materials, seven complete backups, and temporary snapshot space. With the default 2 GB material limit, approximately **25 GB** provides room for backups, but the growing message ledger also needs monitoring. All backups on the same host can be lost with that host: copy them to private off-host storage regularly.

| Setting | Required/default | Meaning |
| --- | --- | --- |
| `DISCORD_TOKEN` | Required secret | Bot token; never in GitHub |
| `GUILD_ID` | Required | One Discord server ID |
| `OWNER_ID` | Required | Only user permitted to adjust coins/manage official shop |
| `DATA_DIR` | `./data` | Persistent database and `materials/` |
| `BACKUP_DIR` | `./backups` | Persistent private backup archives, separate from DATA_DIR |
| `BACKUP_INTERVAL_HOURS` | `24` | Periodic snapshot interval |
| `BACKUP_KEEP` | `7` | Latest successful archives retained; startup/manual backups also count |
| `MAX_UPLOAD_MB` | `8` | Conservative per-attachment cap; keep within Discord delivery limits |
| `STORAGE_LIMIT_MB` | `2048` | All stored materials, including withdrawn items |
| `MAX_LISTINGS_PER_USER` | `25` | Active marketplace listings per member |
| `LOG_LEVEL` | `INFO` | Runtime log level |

`DATA_DIR` and `BACKUP_DIR` must be distinct, non-nested directories. Both must survive rebuilds. Uploaded materials and production databases belong on the disk, never in GitHub or the Docker image.

Native build command:

```sh
python -m pip install -r requirements.lock && python scripts/build.py
```

Native start command:

```sh
python dist/redline.pyz
```

The build creates a source-only zipapp. Runtime dependencies are installed separately from the exact lockfile. Docker handles both steps. Migrations are automatically applied once on startup, transactionally, after backing up an existing database.

## Deploy from GitHub to Render

Render documents both continuously running [background workers](https://render.com/docs/background-workers) and [persistent disks for paid workers](https://render.com/docs/disks). This route requires a paid worker and disk; check the displayed price before ordering. No hosting purchase or deployment was performed for you.

1. Push the repository and wait for all GitHub Actions checks to pass.
2. Sign into <https://dashboard.render.com/>. Choose **New > Background Worker**.
3. Connect GitHub and allow Render access to your private `redline-society-bot` repository. Select that repository and branch `main`.
4. Select **Python** as the runtime and a continuously running paid instance. Set build and start commands to the native commands above. Keep the instance count at **1**.
5. Set `PYTHON_VERSION` to a supported Python 3.13 or 3.14 patch release. The included optional `render.yaml` defaults to 3.13.11; if unavailable in your region/runtime, select a currently supported release in that range.
6. Add a persistent disk mounted at `/var/data`. Use around 25 GB with the default quotas, or reduce `STORAGE_LIMIT_MB` to fit a smaller disk and its backups.
7. Add secret values for `DISCORD_TOKEN`, `GUILD_ID`, `OWNER_ID`. Set `DATA_DIR=/var/data/redline` and `BACKUP_DIR=/var/data/backups`. Optional values match `.env.example`. Do not upload `.env` to GitHub.
8. Turn automatic deploys off initially. Create the worker after reviewing its price. Watch logs for `Slash commands synced` and `Redline Society bot connected`.
9. Test `/daily`, owner `/coins`, and a sample package purchase in Discord. Restart the service, then confirm the balance and `/download` still work. Use a small test file you own.
10. For later updates, make a backup, wait for green CI, then choose **Manual Deploy > Deploy latest commit**. Keep the same service and attached disk. A disk-backed deployment briefly stops the old process before starting the new one; expect short downtime.

An optional Blueprint is included as `render.yaml`: choose **New > Blueprint** and connect this repository if you prefer that route. Review all plan, disk, secret and Python settings before creation. No Blueprint has been deployed or validated against your account.

To create a manual backup from the Render service's shell:

```sh
PYTHONPATH=src python -m redline.backup create
```

Use the service's disk/shell access to copy these private archives to your backup destination. Disk snapshots alone are not a substitute for the application's SQLite-consistent backups and a tested restore.

## Deploy on a VPS with Docker Compose

1. Create a Linux VPS (for example Ubuntu) with enough persistent disk space. Install Docker Engine and the Compose plugin using [Docker's official Ubuntu guide](https://docs.docker.com/engine/install/ubuntu/). Enable Docker at boot: `sudo systemctl enable --now docker`.
2. Install Git: `sudo apt-get update` then `sudo apt-get install -y git`. Authenticate to GitHub with a read-only deploy key for this repository or your usual secure credential method. Never put a personal access token directly in a command URL.
3. Clone the private repository and enter it:

```sh
git clone git@github.com:YOUR_USERNAME/redline-society-bot.git
cd redline-society-bot
cp .env.example .env
chmod 600 .env
nano .env
```

4. Fill the three required values and save (Nano: Ctrl+O, Enter, Ctrl+X). Compose overrides the two directory variables to its persistent volume paths.
5. Build/start and inspect:

```sh
docker compose up -d --build
docker compose ps
docker compose logs --tail=100 -f bot
```

Press Ctrl+C to stop following logs; the worker continues in the background. If your Docker account requires it, prefix Docker commands with `sudo` consistently. No inbound ports are exposed.

The image runs as UID/GID **10001**, drops Linux capabilities, uses a read-only root filesystem and writable data/backups volumes, and never copies private `.env` files or materials. Named volumes are explicitly called `redline-society-data` and `redline-society-backups`; keep these names unchanged. Docker initializes new named volumes with the image's directory ownership. If substituting bind mounts, create directories owned by UID 10001 first.

`restart: unless-stopped` restarts a crashed process and restores it after host reboots when Docker is enabled. SIGTERM/Ctrl+C stop new operations and allow in-flight commands up to 100 seconds before closing Discord and making a final backup. Compose allows two minutes for shutdown. Health is checked from a readiness heartbeat; Docker reports unhealthy status but **does not restart solely for an unhealthy health check**. The bot reconnects through discord.py and closes after ten minutes without readiness so the supervisor can restart it. Monitor health and errors externally as well.

Use `docker compose logs --tail=200 bot` for logs. Compose rotates JSON logs at 10 MB with three retained files. Application logs omit attachment URLs, tokens and file contents. Do not enable verbose HTTP tracing with secrets present.

## Back up, update, and roll back safely

### Backup

Backups run at startup, every configured interval, before migrations of an existing database, and during graceful shutdown. They use SQLite's backup API rather than copying a live WAL database. Each ZIP contains `bot.db`, every referenced material (including withdrawn listings), and SHA-256 checksums. Archives publish only after successful completion. Failed backups do not replace previous archives.

Create a backup manually:

```sh
docker compose exec bot python -m redline.backup create
docker compose exec bot ls -lh /app/storage/backups
mkdir -p private-backups
docker compose cp bot:/app/storage/backups/. ./private-backups/
```

Copy `private-backups` to encrypted, access-controlled storage on another machine. **Do not commit that folder.** It contains member balances and purchased materials. If creating this folder inside your checkout, add `private-backups/` to your local `.git/info/exclude`; the supplied `.gitignore` also excludes it. Check backups regularly, and test a restore. Retention counts archives, not days, so repeated restarts/manual backups reduce historical coverage.

### Update

1. Commit code changes and push. Wait for GitHub Actions to pass.
2. On the server, create and copy an off-host backup with the commands above. Record the current revision: `git rev-parse HEAD`.
3. Download and build the update while the current bot is still running:

```sh
git pull --ff-only
docker compose build
```

4. If the build succeeds, replace the worker:

```sh
docker compose up -d --no-deps bot
docker compose ps
docker compose logs --tail=100 bot
```

5. Confirm `/balance`, `/inventory`, and an old `/download` still work. The same named volumes preserve balances, cooldowns, purchases, listings and files. `.env` stays private and untouched by Git.
6. Never run `docker compose down -v`, delete/prune these volumes, change their names, or copy an old database over the live one. Those actions destroy or split state. Ordinary `docker compose down` preserves named volumes, but causes downtime.

For a **code-only rollback** with a compatible schema, check out your recorded previous commit, build it, and run `docker compose up -d --no-deps bot`. Future migrations must be reviewed for backward compatibility; do not assume old code can read a new schema.

### Verified restore into a new volume

Restore loses changes made after the backup. Stop the worker before switching storage. Keep the existing volumes intact so the operation remains reversible. Replace `BACKUP_FILE.zip` with the exact archive you chose.

```sh
docker compose stop bot
docker volume create redline-society-restored
docker run --rm --user 0:0 --entrypoint chown -v redline-society-restored:/restore redline-society-bot:local 10001:10001 /restore
docker run --rm --entrypoint python -v redline-society-backups:/archives:ro -v redline-society-restored:/restore redline-society-bot:local -m redline.backup restore /archives/BACKUP_FILE.zip --target /restore
```

The restore tool refuses a non-empty target, rejects unsafe paths, verifies every checksum and checks database integrity. Now create `compose.restore.yaml` locally:

```yaml
volumes:
  redline-data:
    name: redline-society-restored
```

Start using the restored volume:

```sh
docker compose -f compose.yaml -f compose.restore.yaml up -d bot
```

Use those same two `-f` flags for later commands while this override is active, or update your private deployment configuration to point to the restored volume permanently. Use code compatible with the backup's schema. Keep the original data volume until you have verified balances, purchase access and materials. Do not restore over an active worker.

## Development and CI

```sh
python -m pip install -r requirements-dev.lock
python -m pip check
python -m mypy src
python -m unittest discover -s tests -v
python scripts/build.py
docker build -t redline-ci .
```

CI runs type checks, tests, production zipapp build and Docker build without a Discord token or production data. Tests cover persistent cooldowns, owner checks, atomic accounting, simultaneous purchases, duplicate deliveries, withdrawn listing entitlements, backup retention/restore, duplicate-worker locking and command serialization. Integration tests use mocked Discord interactions; you must still test invitation permissions and real delivery on your own server.

To update dependencies, resolve them in a clean Python environment, regenerate exact runtime/dev lockfiles, run the full CI matrix, and review the diff. Do not replace pinned dependencies with unbounded `latest` installs on the production server. Python base-image patch/security updates are intentionally picked up on Docker rebuild; for strict image reproducibility, pin a reviewed image digest in your deployment.

## Limits and troubleshooting

- **Offline:** check token, server ID, outbound connectivity, logs, and that the host isn't sleeping. An invalid token exits; fix the host secret and restart.
- **Manage Roles error:** put the bot role above the item role and grant Manage Roles. Roles with dangerous permissions cannot be sold.
- **Delivery failed:** use `/inventory` and `/download`. The permanent purchase is kept even if Discord fails after the debit. Restore a missing file from backup; do not sell a new copy to the same buyer as a workaround.
- **Upload exceeds Discord delivery limit:** the default is 8 MB. Larger uploads require your bot/server's actual delivery limit to support them; increasing the environment value does not increase Discord's limit.
- **Storage full:** withdrawn files remain for prior purchasers. Increase the disk/quota; do not delete files blindly. The quota limits materials only, not the database/backups.
- **Backup fails at startup:** startup fails closed rather than migrate without a backup. Check free space, referenced file availability and permissions; repair or restore the data.
- **Second-worker lock:** stop the old instance. Never run two copies on separate disks for the same server.
- **Safe moderation:** withdrawing a package prevents new sales but preserves existing access by design. This version does not include a purchase revocation/moderation purge command.

See `VALIDATION.md` for what was and was not tested in the authoring environment.
