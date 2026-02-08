"""
Market services — yfinance wrapper for fetching prices, dividends, and ticker info.
"""

import logging
import os
import shutil
import tempfile
from datetime import date, datetime, timedelta
from typing import Optional

import requests as _requests_lib
import yfinance as yf

from app.extensions import db
from app.models import BackfillQueue, DailyPrice, Dividend, Ticker


# ---------------------------------------------------------------------------
# Workaround: curl_cffi (used by yfinance >=1.0) cannot handle non-ASCII
# characters in the CA-bundle path on Windows.  If the certifi cacert.pem
# lives under such a path, copy it to a temp location and point curl at it.
# ---------------------------------------------------------------------------
def _fix_curl_cffi_ssl():
    try:
        import certifi
        ca_path = certifi.where()
        if os.name == "nt" and not ca_path.isascii():
            tmp_dir = os.path.join(tempfile.gettempdir(), "pea_tracker_certs")
            os.makedirs(tmp_dir, exist_ok=True)
            dest = os.path.join(tmp_dir, "cacert.pem")
            if not os.path.exists(dest) or os.path.getmtime(ca_path) > os.path.getmtime(dest):
                shutil.copy2(ca_path, dest)
            os.environ.setdefault("CURL_CA_BUNDLE", dest)
            logger.debug("Set CURL_CA_BUNDLE=%s (non-ASCII path workaround)", dest)
    except Exception as e:
        logger.debug("curl_cffi SSL workaround skipped: %s", e)


logger = logging.getLogger(__name__)
_fix_curl_cffi_ssl()


# ---------------------------------------------------------------------------
# Ticker search & metadata
# ---------------------------------------------------------------------------

def search_tickers(query: str, max_results: int = 8) -> list[dict]:
    """Search Yahoo Finance for tickers matching *query*.

    Uses Yahoo's public autocomplete/search API directly via requests,
    which is more reliable than yfinance's Search class (removed / broken
    across versions).
    """
    import requests as _requests

    url = "https://query2.finance.yahoo.com/v1/finance/search"
    params = {
        "q": query,
        "quotesCount": max_results,
        "newsCount": 0,
        "listsCount": 0,
        "lang": "en-US",
    }
    headers = {"User-Agent": "Mozilla/5.0"}

    try:
        resp = _requests.get(url, params=params, headers=headers, timeout=8)
        resp.raise_for_status()
        quotes = resp.json().get("quotes", [])[:max_results]
        return [
            {
                "symbol": q.get("symbol", ""),
                "name": q.get("shortname") or q.get("longname", ""),
                "exchange": q.get("exchange", ""),
                "type": q.get("quoteType", ""),
            }
            for q in quotes
            if q.get("symbol")
        ]
    except Exception as e:
        logger.warning("Ticker search failed for '%s': %s", query, e)
        return []


def get_or_create_ticker(symbol: str) -> Ticker:
    """Return existing Ticker row or create one, populating metadata from Yahoo."""
    symbol = symbol.upper().strip()
    ticker = Ticker.query.filter_by(symbol=symbol).first()
    if ticker:
        return ticker

    # Fetch metadata from Yahoo
    info = {}
    try:
        yf_ticker = yf.Ticker(symbol)
        info = yf_ticker.info or {}
    except Exception as e:
        logger.warning("Could not fetch info for %s: %s", symbol, e)

    ticker = Ticker(
        symbol=symbol,
        name=info.get("shortName") or info.get("longName") or symbol,
        exchange=info.get("exchange", ""),
        currency=info.get("currency", "EUR"),
        sector=info.get("sector", ""),
        last_updated=datetime.utcnow(),
    )
    db.session.add(ticker)
    db.session.flush()  # get the id
    return ticker


# ---------------------------------------------------------------------------
# Price fetching
# ---------------------------------------------------------------------------

def fetch_prices_for_tickers(
    ticker_ids_dates: dict[int, date],
) -> dict[int, int]:
    """
    Fetch historical daily prices from yfinance for multiple tickers.

    Args:
        ticker_ids_dates: mapping of ticker_id -> earliest date needed

    Returns:
        mapping of ticker_id -> number of rows upserted
    """
    if not ticker_ids_dates:
        return {}

    # Resolve symbols
    tickers = Ticker.query.filter(Ticker.id.in_(ticker_ids_dates.keys())).all()
    id_to_symbol = {t.id: t.symbol for t in tickers}
    symbol_to_id = {t.symbol: t.id for t in tickers}

    symbols = list(id_to_symbol.values())
    if not symbols:
        return {}

    # Find the global earliest date (minus 5 days buffer for weekends)
    earliest = min(ticker_ids_dates.values()) - timedelta(days=5)

    logger.info("Fetching prices for %d tickers from %s", len(symbols), earliest)

    try:
        df = yf.download(
            symbols,
            start=earliest.isoformat(),
            end=(date.today() + timedelta(days=1)).isoformat(),
            threads=True,
            repair=False,
            progress=False,
        )
    except Exception as e:
        logger.error("yf.download failed: %s", e)
        return {}

    if df.empty:
        logger.warning("yf.download returned empty dataframe")
        return {}

    result_counts = {}

    # yfinance >=1.0 always returns MultiIndex columns (Price, Ticker),
    # even for a single symbol.  Normalise to simple columns per symbol.
    for symbol in symbols:
        ticker_id = symbol_to_id[symbol]
        try:
            if symbol in df.columns.get_level_values(-1):
                ticker_df = df.xs(symbol, level="Ticker", axis=1)
            else:
                logger.warning("No data returned for %s", symbol)
                continue

            count = 0
            for idx, row in ticker_df.iterrows():
                price_date = idx.date() if hasattr(idx, "date") else idx
                close_val = row.get("Close")
                if close_val is None or (hasattr(close_val, "__float__") and str(close_val) == "nan"):
                    continue

                existing = DailyPrice.query.filter_by(
                    ticker_id=ticker_id, date=price_date
                ).first()

                if existing:
                    existing.open = _safe_float(row.get("Open"))
                    existing.high = _safe_float(row.get("High"))
                    existing.low = _safe_float(row.get("Low"))
                    existing.close = _safe_float(row.get("Close"))
                    existing.volume = _safe_int(row.get("Volume"))
                else:
                    dp = DailyPrice(
                        ticker_id=ticker_id,
                        date=price_date,
                        open=_safe_float(row.get("Open")),
                        high=_safe_float(row.get("High")),
                        low=_safe_float(row.get("Low")),
                        close=_safe_float(row.get("Close")),
                        volume=_safe_int(row.get("Volume")),
                    )
                    db.session.add(dp)
                count += 1

            result_counts[ticker_id] = count

        except Exception as e:
            logger.error("Error processing prices for %s: %s", symbol, e)
            result_counts[ticker_id] = 0

    db.session.commit()
    logger.info("Upserted prices: %s", result_counts)
    return result_counts


def fetch_dividends_for_tickers(ticker_ids: list[int]):
    """Fetch dividend history from yfinance and upsert."""
    tickers = Ticker.query.filter(Ticker.id.in_(ticker_ids)).all()

    for t in tickers:
        try:
            yf_ticker = yf.Ticker(t.symbol)
            divs = yf_ticker.dividends
            if divs is None or divs.empty:
                continue
            for dt_idx, amount in divs.items():
                d = dt_idx.date() if hasattr(dt_idx, "date") else dt_idx
                existing = Dividend.query.filter_by(ticker_id=t.id, date=d).first()
                if not existing and amount > 0:
                    db.session.add(
                        Dividend(ticker_id=t.id, date=d, amount_per_share=float(amount))
                    )
        except Exception as e:
            logger.warning("Dividend fetch failed for %s: %s", t.symbol, e)

    db.session.commit()


# ---------------------------------------------------------------------------
# Backfill logic
# ---------------------------------------------------------------------------

def request_backfill(ticker_id: int, from_date: date):
    """
    Add a backfill request to the queue if needed.
    Checks whether we already have price data covering this date.
    """
    earliest_existing = (
        db.session.query(db.func.min(DailyPrice.date))
        .filter_by(ticker_id=ticker_id)
        .scalar()
    )

    if earliest_existing and earliest_existing <= from_date:
        return  # Already covered

    # Check if there's already a pending backfill covering this date
    existing_pending = BackfillQueue.query.filter_by(
        ticker_id=ticker_id, status="PENDING"
    ).first()

    if existing_pending:
        if from_date < existing_pending.from_date:
            existing_pending.from_date = from_date
            db.session.commit()
        return

    bq = BackfillQueue(
        ticker_id=ticker_id,
        from_date=from_date,
        status="PENDING",
    )
    db.session.add(bq)
    db.session.commit()


def process_backfill_queue() -> dict:
    """
    Process all PENDING backfill requests.
    Returns summary of what was processed.
    """
    pending = BackfillQueue.query.filter_by(status="PENDING").all()
    if not pending:
        return {"processed": 0}

    # Group by ticker, take earliest date
    ticker_dates: dict[int, date] = {}
    for bq in pending:
        bq.status = "PROCESSING"
        if bq.ticker_id not in ticker_dates or bq.from_date < ticker_dates[bq.ticker_id]:
            ticker_dates[bq.ticker_id] = bq.from_date
    db.session.commit()

    # Fetch prices
    result = fetch_prices_for_tickers(ticker_dates)

    # Fetch dividends
    fetch_dividends_for_tickers(list(ticker_dates.keys()))

    # Update queue status
    for bq in pending:
        rows = result.get(bq.ticker_id, 0)
        if rows > 0 or bq.ticker_id in result:
            bq.status = "DONE"
        else:
            bq.status = "FAILED"
            bq.error_message = "No data returned from Yahoo Finance"
    db.session.commit()

    return {"processed": len(pending), "results": result}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_float(val) -> Optional[float]:
    try:
        f = float(val)
        return None if f != f else f  # NaN check
    except (TypeError, ValueError):
        return None


def _safe_int(val) -> Optional[int]:
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return None
