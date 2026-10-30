import asyncio
import logging
import os
import signal

from .runtime import FileLock

from .backup import create_backup
from .bot import Bot
from .config import Config
from .store import Store


async def run(config: Config) -> None:
    # Back up existing state before automatic migrations touch it.
    if (config.data / "bot.db").exists():
        await asyncio.to_thread(create_backup, config.data, config.backups, config.backup_keep)
    store = Store(config.data / "bot.db", config.owner_id)
    bot = Bot(config, store)
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            signal.signal(sig, lambda *_: loop.call_soon_threadsafe(stop.set))
    worker = asyncio.create_task(bot.start(config.token, reconnect=True))
    async def wait_stop() -> None:
        await stop.wait()
    waiter = asyncio.create_task(wait_stop())
    try:
        done, _ = await asyncio.wait({worker, waiter}, return_when=asyncio.FIRST_COMPLETED)
        if worker in done:
            await worker
    finally:
        await bot.shutdown()
        waiter.cancel()
        await asyncio.gather(waiter, worker, return_exceptions=True)
        try:
            await asyncio.to_thread(create_backup, config.data, config.backups, config.backup_keep)
        finally:
            store.close()


def main() -> None:
    config = Config.load()
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("discord.http").setLevel(logging.WARNING)
    config.data.mkdir(parents=True, exist_ok=True)
    try:
        # Prevent accidental duplicate workers using the same database volume.
        with FileLock(str(config.data / "worker.lock"), timeout=0):
            asyncio.run(run(config))
    except TimeoutError:
        raise SystemExit("Another worker already owns this data directory.") from None
    except Exception as exc:
        logging.getLogger("redline").error("worker_exit type=%s (check configuration, permissions and logs)", type(exc).__name__)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()

