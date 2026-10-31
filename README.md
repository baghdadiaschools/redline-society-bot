# Redline Society bot

Python Discord bot for one server. R-coins are community points. The old member marketplace, `/shop`, `/market`, `/buy`, `/sell`, `/inventory`, `/download`, `/remove`, and `/race` commands are removed. New products are owner managed. Casino-style commands are free practice without stakes or coin rewards.

## Discord setup

1. In [Discord Developer Portal](https://discord.com/developers/applications), select this application, open **Bot**, and enable **Message Content Intent**. Prefix `?` commands need it. Save changes. The token stays private.
2. Grant the bot **View Channels**, **Send Messages**, **Read Message History**, **Embed Links**, **Attach Files**, **Manage Roles**, **Moderate Members**, **Kick Members**, and **Ban Members**. It does not need Administrator. Move its role above roles it must give or remove and members it must moderate. Discord hierarchy and channel permissions still apply.
3. Keep `DISCORD_TOKEN`, `GUILD_ID` and `OWNER_ID` privately in Render Environment or `.env` on your server. Do not commit them to GitHub.
4. Invite with `bot` and `applications.commands` scopes. Try `/help` and `?help` in your server.

## Coins and commands

Members gain 1 R-coin for each eligible server message, with a 30-second per-member cooldown. `/daily` gives 100 every 24 hours. Bots, webhooks, other servers and DMs do not earn coins. `/balance [member]` and `/leaderboard` show balances. Owner-only `/coins member mode amount` and `/coins_all mode confirmation amount` adjust balances; bulk changes require `CONFIRM ALL` exactly. Slash replies are private.

### Moderation (server messages)

| Command | Role ID allowed | Effect |
| --- | --- | --- |
| `?warn @member reason` | `1565764096773849210` | Record a warning |
| `?kick @member reason` | `1565777948840173729` | Kick |
| `?mute @member 30m reason` | `1565764096773849210` | Discord timeout; use `m`, `h`, or `d`, max 28 days |
| `?ban @member reason` | `1565768824404443346` | Permanent ban |
| `?role give @member @role` | `1565768824404443346` or `1565778010546638949` | Add a role |
| `?role delete @member @role reason` | Same two IDs | Remove a role |
| `?history @member` | `1565764096773849210` | Show up to 20 recent actions performed **through this bot** |

The configured owner may use moderation commands too. These role IDs are exact, not permission inheritance. The bot refuses to target itself, the owner, or a member above the moderator's role. Discord's role hierarchy and actual bot permissions provide another check. `?history` cannot reconstruct moderation performed outside this bot or before the database existed.

### Owner marketplace

1. In the server, set the posting channel with `?marketplace channel #your-channel`.
2. To sell a cosmetic role, use `?marketrole add @role 500` in the server. The bot posts a public card with its price and a Purchase button. Use `?marketrole remove PRODUCT_ID` to withdraw it. Roles can be bought once.
3. To sell a file item, **DM the bot**: `?marketplace item add Title | Description | 500 | once`. The bot asks for public preview attachment(s) in your next DM; send them or `skip`. It then asks for private delivery file(s) in another DM. Send one to five files. The hidden files are never posted to the public channel. The bot posts a card with title, description, price, preview files and a Purchase button. Use `?marketplace item remove PRODUCT_ID` to withdraw it.
4. Replace `once` with `repeat` for unlimited repeat purchases, or `limit:3` for up to three purchases **per member**. Product IDs appear in the cards.

The **owner** supplies hidden files. The buyer receives them only in a DM after purchasing; buyers do not upload hidden files. Public preview files are separate. Each uploaded file has the default 8 MB cap; total materials default to 2 GB. The bot does not scan, execute, or unpack uploads. A buyer can copy a received file, so do not assume DRM.

The button checks coins and purchase limits atomically. If enough coins are available, a purchase creates an order, debits the buyer, delivers a role or DMs the hidden files, and DMs the owner the buyer's member ID and order ID. If delivery fails after charging, the buyer can enable DMs and send `?claim ORDER_ID` to the bot; `?orders` lists their recent orders. Retrying delivery does not charge again. Removing a product prevents new purchases but retains prior order access while storage survives. No real money or cash-out exists.

`?roulette` and `?blackjack` are free practice responses: no R-coins are spent or awarded. They do not advertise biased odds or offer wagering.

## Current free Render service

The private GitHub repository is [baghdadiaschools/redline-society-bot](https://github.com/baghdadiaschools/redline-society-bot). Render service `srv-db8aqc8u01pc73f57h3g` (still named `baghdadia-school`) builds this repository's `main` branch. Build command:

```sh
python -m pip install -r requirements.lock && python scripts/build.py
```

Start command for the existing free web test service:

```sh
PYTHONPATH=src python -m redline.web
```

Set `DISCORD_TOKEN`, `GUILD_ID`, `OWNER_ID` in Render Environment. A successful log includes `Slash commands synced for configured server` and `Redline Society bot connected`. Your PC may be off. **Free Render web services sleep after inactivity and their local filesystem is erased on spin-down, restart or redeploy.** Balances, warnings, orders, products, private files and backups can vanish. Old public buttons then cannot fulfill orders. Never use this setup for valuable materials or a permanent economy. Do not use an uptime pinger as a substitute for durable storage.

## Durable deployment with Docker Compose

Use one always-on VPS or compatible worker with persistent storage; static hosting cannot run the Discord Gateway connection. Install Docker Engine and Compose, clone the private repository, then in its root:

```sh
cp .env.example .env
# Edit .env privately: DISCORD_TOKEN, GUILD_ID, OWNER_ID
docker compose up -d --build
docker compose logs --tail=100 -f bot
```

The Dockerfile and `compose.yaml` use persistent named volumes for SQLite and materials, and for backup ZIPs. Do not run `docker compose down -v`, rename the volumes, commit `.env`, or copy the live SQLite file without using the backup tool. To update: wait for green GitHub Actions, run `docker compose exec bot python -m redline.backup create`, copy backups off-host, `git pull --ff-only`, `docker compose build`, then `docker compose up -d --no-deps bot`. Verify old orders and balances afterward. Logs are rotated; the worker restarts after crashes and host reboot, handles SIGTERM, and makes automatic SQLite-consistent backups. Single replica only.

Environment defaults: `DATA_DIR=./data`, `BACKUP_DIR=./backups`, `BACKUP_INTERVAL_HOURS=24`, `BACKUP_KEEP=7`, `MAX_UPLOAD_MB=8`, `STORAGE_LIMIT_MB=2048`, `LOG_LEVEL=INFO`. Data and backup directories must be separate and persistent. Keep backups off-host and private because they contain purchase files and member data. Run `python -m unittest discover -s tests -v`, `python -m mypy src`, and `python scripts/build.py` for development; GitHub Actions checks them without production secrets.
