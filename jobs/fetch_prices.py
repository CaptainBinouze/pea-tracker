"""
Daily price fetcher — scheduled by Railway Cron.
Usage: python -m jobs.fetch_prices
Cron schedule: 0 17 * * 1-5  (18h CET, weekdays only)

Deploy as a **separate Cron Job service** on Railway (not inside the web service).
"""

import sys
import os
from datetime import date, timedelta

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.extensions import db
from app.models import Ticker, Alert, Transaction
from app.market.services import fetch_prices_for_tickers, fetch_dividends_for_tickers, process_backfill_queue
from app.alerts.services import evaluate_alerts
from app.portfolio.services import compute_snapshots, ensure_snapshots_uptodate

# How many days back to fetch on each run (covers weekends + missed days)
LOOKBACK_DAYS = 7


def run():
    app = create_app()
    with app.app_context():
        # 1. Process any pending backfills first
        print("[CRON] Processing backfill queue...")
        process_backfill_queue()

        # 2. Fetch recent prices for all tickers in use
        tickers = Ticker.query.all()
        if not tickers:
            print("[CRON] No tickers to update.")
            return

        earliest = date.today() - timedelta(days=LOOKBACK_DAYS)
        ticker_ids_dates = {t.id: earliest for t in tickers}
        symbols = [t.symbol for t in tickers]
        print(f"[CRON] Fetching prices for {len(symbols)} tickers from {earliest}: {symbols}")

        result = fetch_prices_for_tickers(ticker_ids_dates)
        print(f"[CRON] Prices updated: {result}")

        # 3. Fetch dividends
        print("[CRON] Fetching dividends...")
        fetch_dividends_for_tickers([t.id for t in tickers])
        print("[CRON] Dividends updated.")

        # 4. Recompute portfolio snapshots for all users with transactions
        #    Uses ensure_snapshots_uptodate to detect and fill any gaps
        print("[CRON] Recomputing portfolio snapshots (with gap detection)...")
        user_ids = db.session.query(Transaction.user_id).distinct().all()
        for (uid,) in user_ids:
            ensure_snapshots_uptodate(uid)
        print(f"[CRON] Snapshots recomputed for {len(user_ids)} user(s).")

        # 5. Evaluate price alerts
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
