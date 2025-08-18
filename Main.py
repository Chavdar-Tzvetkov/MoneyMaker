# main.py
import argparse
import os
import sys
from typing import List

# Force working directory to the project root where main.py is
os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.getcwd())

from smart_live_trading import main as ai_main
from utils.scheduler import start_scheduler
from live_trading import run_live_trading
from mt5_api import initialize_mt5, shutdown_mt5
import config


def parse_args():
    p = argparse.ArgumentParser(description="Trading Bot")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument('--live', action='store_true',
                      help='Run live_trading (classic, AI decider OFF)')
    mode.add_argument('--live-ai', action='store_true',
                      help='Run live_trading with AI meta-decider enabled')
    mode.add_argument('--ai', action='store_true',
                      help='Run the standalone AI meta-controller demo (no orders)')

    p.add_argument('--loop-delay', type=int, default=5,
                   help='AI loop delay (smart_live_trading only)')
    p.add_argument('--symbols', type=str, default="",
                   help='Override symbols list: comma-separated (e.g. "AAPL,MSFT,EURUSD=X")')
    return p.parse_args()


def _merge_symbols(override: str) -> List[str]:
    if override:
        raw = [s.strip() for s in override.split(",") if s.strip()]
    else:
        raw = list(getattr(config, "INSTRUMENTS", [])) + list(getattr(config, "FOREX_SYMBOLS", []))
    # de-dup while preserving order
    seen, out = set(), []
    for s in raw:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _print_env_summary():
    use_meta = os.getenv("USE_META_DECIDER", "0")
    hedge_on = os.getenv("HEDGE_ENABLED", "0")
    max_hour = os.getenv("MAX_TRADES_PER_HOUR", str(getattr(config, "RATE_LIMIT", {}).get("MAX_TRADES_PER_HOUR", 6)))
    print(f"[Flags] USE_META_DECIDER={use_meta} | HEDGE_ENABLED={hedge_on} | MAX_TRADES_PER_HOUR={max_hour}")


if __name__ == "__main__":
    args = parse_args()
    symbols = _merge_symbols(args.symbols)

    if args.live_ai:
        # Live trading with AI decider (this is the fully automated system)
        os.environ["USE_META_DECIDER"] = "1"   # make sure the live loop sees it
        config.LIVE_TRADING = True
        print("[Mode] LIVE trading mode (AI decider ON).")
        _print_env_summary()
        initialize_mt5()
        try:
            run_live_trading()
        finally:
            shutdown_mt5()

    elif args.live:
        # Classic live trading (AI decider OFF)
        os.environ.setdefault("USE_META_DECIDER", "0")
        config.LIVE_TRADING = True
        print("[Mode] LIVE trading mode (classic).")
        _print_env_summary()
        initialize_mt5()
        try:
            run_live_trading()
        finally:
            shutdown_mt5()

    elif args.ai:
        # Standalone AI meta-controller runner (no order routing; demo/learning only)
        print("[Mode] AI meta-controller runner (no orders).")
        initialize_mt5()  # keep MT5 available for FX data if needed
        try:
            ai_main(symbols, loop_delay=args.loop_delay)
        finally:
            shutdown_mt5()

    else:
        print("[Mode] Dry-run mode (scheduler).")
        start_scheduler()
