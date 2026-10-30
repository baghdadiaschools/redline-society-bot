# Free Render test deployment

This mode was explicitly selected as a temporary test. Render may sleep, missed
messages earn no rewards, and restarts/redeployments can erase the entire local
economy, listings, purchases, materials and backups. It is not the durable worker
deployment documented in README.md. Do not sell valuable materials in this mode.

Reuse a free web service by connecting the `redline-society-bot` repository,
branch `main`, with Python 3 as runtime. Keep the Free compute plan and no disk.

Build: `python -m pip install -r requirements.lock && python scripts/build.py`

Start: `PYTHONPATH=src python -m redline.web`

Set PYTHON_VERSION=3.13.11, DATA_DIR=./data, BACKUP_DIR=./backups.
Enter DISCORD_TOKEN, GUILD_ID and OWNER_ID privately in Render Environment.
The HTTP page reports missing variable names without revealing values. Once
all three are configured, restart/redeploy the service to connect Discord.

For public listing cards, grant the bot View Channel, Send Messages and Embed
Links in the selected channel. Run /market_channel first. /sell posts a public
description card with a Buy button; /role_add and /pack_add post there too.
The owner can edit any active listing with /listing_edit or withdraw it with
/remove. /listing_post publishes an existing unposted item. Buttons and cards
cannot restore listings when Render's free local storage is erased on sleep,
restart or redeploy; old cards then show an unavailable listing.
No automatic pings or other attempts to bypass hosting limits are included.

Switching the existing school service to this repository replaces its live
website. Keep the original repository to allow a later rollback.

