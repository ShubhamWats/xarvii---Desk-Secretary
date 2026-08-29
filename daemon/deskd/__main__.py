import argparse
import logging
import sys

from .config import apply_demo_overrides, load_config
from .server import serve


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="deskd", description="Desk secretary daemon")
    ap.add_argument("--config", help="path to config.toml")
    ap.add_argument("--host")
    ap.add_argument("--ws-port", type=int)
    ap.add_argument("--verbose", "-v", action="store_true")
    ap.add_argument("--demo", action="store_true",
                    help="echo STT/LLM + null TTS: full loop with zero models/hardware")
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    cfg = load_config(args.config)
    if args.demo:
        apply_demo_overrides(cfg)
        logging.getLogger().info("DEMO MODE: echo stt/llm, no tts audio")
    if args.host:
        cfg.server.ws_host = args.host
    if args.ws_port:
        cfg.server.ws_port = args.ws_port

    try:
        import asyncio

        asyncio.run(serve(cfg))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
