"""python -m intake [--console] [--mock]: Telegram-бот (long polling) или терминальная проверка."""
import asyncio
import logging
import sys

from dotenv import load_dotenv


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    from .config import ConfigError, load
    try:
        cfg = load()
    except ConfigError as e:
        print(e)
        raise SystemExit(1)
    from .core import Core
    from .llm import get_provider
    try:
        provider = get_provider("mock" if "--mock" in argv else None, cfg)
    except RuntimeError as e:
        print(e)
        raise SystemExit(1)
    core = Core(cfg, provider=provider)
    if "--console" in argv:
        from .messengers.console import run_console
        asyncio.run(run_console(core))
    else:
        from .messengers.telegram import Telegram
        asyncio.run(Telegram(core).run())


if __name__ == "__main__":
    main()
