"""Optional HTTP entry point for a sleeping, ephemeral Render free web service."""
import asyncio
import logging
import os

from aiohttp import web

from .__main__ import run
from .config import Config
from .runtime import FileLock, load_dotenv


async def serve() -> None:
    load_dotenv()
    logging.basicConfig(level=logging.INFO)
    missing = [key for key in ("DISCORD_TOKEN", "GUILD_ID", "OWNER_ID")
               if not os.getenv(key, "").strip()]
    app = web.Application()

    async def status(request: web.Request) -> web.Response:
        return web.json_response({
            "service": "Redline Society bot",
            "mode": "free-test",
            "configuration": "missing" if missing else "configured",
            "missing_variables": missing,
            "storage": "ephemeral; restarts may erase balances and materials",
        }, status=503 if missing else 200)

    app.router.add_get("/", status)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", int(os.getenv("PORT", "10000"))).start()
    logging.warning("FREE TEST MODE: service can sleep and local state is ephemeral")
    try:
        if missing:
            logging.warning("Set the missing Discord variables in Render Environment settings")
            await asyncio.Event().wait()
        else:
            config = Config.load()
            config.data.mkdir(parents=True, exist_ok=True)
            with FileLock(str(config.data / "worker.lock"), timeout=0):
                await run(config)
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(serve())
