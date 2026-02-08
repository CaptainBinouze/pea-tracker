"""
Daily price fetcher — scheduled by Railway Cron.
Usage: python -m jobs.fetch_prices
Cron schedule: 0 17 * * 1-5  (18h CET, weekdays only)
"""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.models import Ticker, Alert
from app.market.services import fetch_prices_for_tickers, fetch_dividends_for_tickers, process_backfill_queue
from app.alerts.services import evaluate_alerts


def run():
    app = create_app()
    with app.app_context():
        # 1. Process any pending backfills first
        print("[CRON] Processing backfill queue...")
        process_backfill_queue()

        # 2. Fetch today's prices for all tickers in use
        tickers = Ticker.query.all()
        if not tickers:
            print("[CRON] No tickers to update.")
            return

        symbols = [t.symbol for t in tickers]
        print(f"[CRON] Fetching prices for {len(symbols)} tickers: {symbols}")

        fetch_prices_for_tickers(symbols, period="5d")
        print("[CRON] Prices updated.")

        # 3. Fetch dividends
        print("[CRON] Fetching dividends...")
        fetch_dividends_for_tickers(symbols)
        print("[CRON] Dividends updated.")

        # 4. Evaluate price alerts
        print("[CRON] Evaluating alerts...")
        triggered = evaluate_alerts()
        if triggered:
            print(f"[CRON] {len(triggered)} alert(s) triggered:")
            for a in triggered:
                print(f"  - {a['ticker_symbol']} {a['condition']} {a['threshold']}")
        else:
            print("[CRON] No alerts triggered.")

        print("[CRON] Done.")


if __name__ == "__main__":
    run()
