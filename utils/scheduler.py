# utils/scheduler.py

import schedule
import time
from live_trading import run_live_trading
import config

def start_scheduler():
    print("[Scheduler] Trading bot started.")

    # Optional immediate run
    run_live_trading()

    # Adjust interval as needed (e.g., 30 minutes = schedule.every(30).minutes)
    schedule.every(30).minutes.do(run_live_trading)

    if config.LIVE_TRADING:
        print("[Scheduler] Running in LIVE mode.")
    else:
        print("[Scheduler] DRY-RUN mode. No real trades will be executed.")

    while True:
        schedule.run_pending()
        time.sleep(1)
