# Free Render test service

The existing service `srv-db8aqc8u01pc73f57h3g`, still named `baghdadia-school`, is connected to the private Redline Society bot GitHub repository. Pushes to `main` automatically redeploy it. Build command: `python -m pip install -r requirements.lock && python scripts/build.py`. Start command: `PYTHONPATH=src python -m redline.web`. Keep `DISCORD_TOKEN`, `GUILD_ID` and `OWNER_ID` in Render Environment, never in GitHub.

Prefix commands require **Message Content Intent** enabled in Discord Developer Portal > Bot. The bot also needs View Channels, Send Messages, Read Message History, Embed Links, Attach Files, Manage Roles, Moderate Members, Kick Members and Ban Members; place its role high enough in the hierarchy. A successful deployment logs `Redline Society bot connected`.

Free web services sleep without inbound HTTP traffic; Discord messages do not wake them. Spin-down, restarts and redeploys erase local SQLite, moderation history, coins, orders, product files and backups. Existing public product cards then lose their backing data. This is a test deployment only. Use persistent storage and an always-on service before selling valuable content or relying on permanent balances.

See README.md for the new owner marketplace setup and moderation commands. Do not run the old `/market_channel`, `/role_add`, `/pack_add`, `/shop`, `/market`, `/sell`, `/buy`, `/inventory`, `/download`, `/remove` or `/race` commands; they have been removed from the bot.

