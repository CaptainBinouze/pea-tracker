"""
Portfolio services — P&L calculations, positions, snapshots.
"""

import logging
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import func

from app.extensions import db
from app.models import DailyPrice, Dividend, PortfolioSnapshot, Ticker, Transaction

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Positions & P&L
# ---------------------------------------------------------------------------

def _compute_holdings(user_id: int) -> dict[int, dict]:
    """
    Compute per-ticker aggregates (qty, cost, realized PnL) for ALL tickers,
    including fully closed positions.  Used by both get_positions() and
    get_portfolio_summary() so the transaction loop runs only once per call.
    """
    transactions = (
        Transaction.query.filter_by(user_id=user_id)
        .order_by(Transaction.date)
        .all()
    )

    holdings: dict[int, dict] = defaultdict(lambda: {
        "qty": Decimal(0),
        "total_cost": Decimal(0),
        "realized_pnl": Decimal(0),
    })

    for tx in transactions:
        h = holdings[tx.ticker_id]
        if tx.type == "BUY":
            h["total_cost"] += tx.quantity * tx.price_per_share + tx.fees
            h["qty"] += tx.quantity
        elif tx.type == "SELL":
            if h["qty"] > 0:
                pru = h["total_cost"] / h["qty"]
                h["realized_pnl"] += (tx.price_per_share - pru) * tx.quantity - tx.fees
                h["total_cost"] -= pru * tx.quantity
                h["qty"] -= tx.quantity

    return holdings


def get_positions(user_id: int, *, _holdings: dict | None = None) -> list[dict]:
    """
    Compute current positions for a user.
    Returns list of dicts with: ticker info, quantity, PRU, current price, P&L, weight.

    If *_holdings* is supplied (from a prior ``_compute_holdings`` call) it is
    reused instead of re-querying all transactions.
    """
    holdings = _holdings if _holdings is not None else _compute_holdings(user_id)

    # Filter to open positions
    open_tids = [tid for tid, h in holdings.items() if h["qty"] > Decimal("0.0001")]
    if not open_tids:
        return []

    # --- Batch-fetch tickers -------------------------------------------------
    tickers_list = Ticker.query.filter(Ticker.id.in_(open_tids)).all()
    tickers_map: dict[int, Ticker] = {t.id: t for t in tickers_list}

    # --- Batch-fetch latest 2 prices per ticker (cross-DB compatible) ------
    from sqlalchemy import literal_column
    from sqlalchemy.orm import aliased

    # Subquery: rank prices per ticker by date descending
    ranked = (
        db.session.query(
            DailyPrice.ticker_id,
            DailyPrice.date,
            DailyPrice.close,
            func.row_number()
            .over(
                partition_by=DailyPrice.ticker_id,
                order_by=DailyPrice.date.desc(),
            )
            .label("rn"),
        )
        .filter(DailyPrice.ticker_id.in_(open_tids))
        .subquery()
    )

    price_rows = (
        db.session.query(
            ranked.c.ticker_id,
            ranked.c.date,
            ranked.c.close,
            ranked.c.rn,
        )
        .filter(ranked.c.rn <= 2)
        .all()
    )

    # Build lookup: ticker_id -> {"latest": (close, date), "prev": close}
    price_lookup: dict[int, dict] = {}
    for tid, dt, close_val, rn in price_rows:
        entry = price_lookup.setdefault(tid, {})
        if rn == 1:
            entry["latest_close"] = close_val
            entry["latest_date"] = dt
        elif rn == 2:
            entry["prev_close"] = close_val

    # --- Build position list -------------------------------------------------
    positions = []
    total_portfolio_value = Decimal(0)

    for ticker_id in open_tids:
        h = holdings[ticker_id]
        ticker = tickers_map.get(ticker_id)
        if not ticker:
            continue

        prices = price_lookup.get(ticker_id, {})
        current_price = prices.get("latest_close")
        price_date = prices.get("latest_date")
        prev_close = prices.get("prev_close", current_price)

        pru = h["total_cost"] / h["qty"] if h["qty"] > 0 else 0
        market_value = h["qty"] * current_price if current_price else 0
        unrealized_pnl = (current_price - pru) * h["qty"] if current_price else 0
        unrealized_pnl_pct = ((current_price / pru) - 1) * 100 if current_price and pru > 0 else 0
        daily_change = ((current_price - prev_close) / prev_close * 100) if current_price and prev_close else 0

        total_portfolio_value += market_value

        positions.append({
            "ticker": ticker,
            "quantity": h["qty"],
            "pru": pru,
            "current_price": current_price,
            "price_date": price_date,
            "market_value": market_value,
            "invested": h["total_cost"],
            "unrealized_pnl": unrealized_pnl,
            "unrealized_pnl_pct": unrealized_pnl_pct,
            "realized_pnl": h["realized_pnl"],
            "daily_change": daily_change,
            "weight": 0,
        })

    # Calculate weights
    for p in positions:
        if total_portfolio_value > 0:
            p["weight"] = (p["market_value"] / total_portfolio_value) * 100

    # Sort by weight descending
    positions.sort(key=lambda p: p["weight"], reverse=True)
    return positions


def get_portfolio_summary(user_id: int) -> dict:
    """Compute portfolio-level summary metrics.

    Internally calls ``_compute_holdings`` **once** and reuses the result
    for both ``get_positions`` and the realized-PnL / dividend totals.
    """
    # Single holdings computation — shared across positions and PnL
    all_holdings = _compute_holdings(user_id)

    positions = get_positions(user_id, _holdings=all_holdings)

    total_value = sum(p["market_value"] for p in positions)
    total_invested = sum(p["invested"] for p in positions)
    total_unrealized = sum(p["unrealized_pnl"] for p in positions)
    total_pnl_pct = ((total_value / total_invested) - 1) * 100 if total_invested > 0 else 0

    # Sum realized PnL across ALL tickers (including fully closed positions).
    total_realized = sum(h["realized_pnl"] for h in all_holdings.values())

    # Dividends — include all tickers the user ever traded, not just open ones
    all_ticker_ids = list(all_holdings.keys())
    total_dividends = _compute_total_dividends(user_id, all_ticker_ids)

    return {
        "positions": positions,
        "total_value": total_value,
        "total_invested": total_invested,
        "total_unrealized_pnl": total_unrealized,
        "total_unrealized_pnl_pct": total_pnl_pct,
        "total_realized_pnl": total_realized,
        "total_dividends": total_dividends,
        "total_return": total_unrealized + total_realized + total_dividends,
        "num_positions": len(positions),
    }


def _compute_total_dividends(user_id: int, ticker_ids: list[int]) -> Decimal:
    """Compute total dividends received based on holdings at each ex-date.

    Uses an in-memory approach: loads all transactions and dividends in two
    queries, then computes holdings at each ex-date in Python.  This avoids
    the previous N+1 pattern (one sub-query per dividend row).
    """
    if not ticker_ids:
        return Decimal(0)

    # 1. Load all relevant transactions (sorted by date)
    transactions = (
        Transaction.query
        .filter(
            Transaction.user_id == user_id,
            Transaction.ticker_id.in_(ticker_ids),
        )
        .order_by(Transaction.date)
        .all()
    )

    # 2. Load all dividends for these tickers
    dividends = (
        Dividend.query
        .filter(Dividend.ticker_id.in_(ticker_ids))
        .order_by(Dividend.date)
        .all()
    )

    if not dividends:
        return Decimal(0)

    # 3. Pre-compute cumulative holdings per ticker at each transaction date
    #    ticker_id -> sorted list of (date, cumulative_qty)
    from bisect import bisect_right

    cum_holdings: dict[int, list[tuple]] = defaultdict(list)
    running: dict[int, Decimal] = defaultdict(Decimal)
    for tx in transactions:
        if tx.type == "BUY":
            running[tx.ticker_id] += tx.quantity
        elif tx.type == "SELL":
            running[tx.ticker_id] -= tx.quantity
        cum_holdings[tx.ticker_id].append((tx.date, running[tx.ticker_id]))

    # 4. For each dividend, binary-search the qty held at ex-date
    total = Decimal(0)
    for div in dividends:
        entries = cum_holdings.get(div.ticker_id)
        if not entries:
            continue
        # bisect on date: find last transaction with date <= div.date
        dates = [e[0] for e in entries]
        idx = bisect_right(dates, div.date) - 1
        if idx < 0:
            continue
        qty = entries[idx][1]
        if qty > 0:
            total += qty * div.amount_per_share

    return total


# ---------------------------------------------------------------------------
# Snapshot computation
# ---------------------------------------------------------------------------

def compute_snapshots(user_id: int, from_date: Optional[date] = None):
    """
    Recompute portfolio snapshots for a user from *from_date* to today.
    Uses LOCF (Last Observation Carried Forward) for weekends/holidays.
    """
    transactions = (
        Transaction.query.filter_by(user_id=user_id)
        .order_by(Transaction.date)
        .all()
    )
    if not transactions:
        return

    start = from_date or transactions[0].date
    end = date.today()
    if start > end:
        return

    # Collect all ticker_ids
    all_ticker_ids = list({tx.ticker_id for tx in transactions})

    # Prefetch all prices for these tickers in range
    prices_query = (
        DailyPrice.query
        .filter(DailyPrice.ticker_id.in_(all_ticker_ids))
        .filter(DailyPrice.date >= start - timedelta(days=7))
        .filter(DailyPrice.date <= end)
        .order_by(DailyPrice.date)
        .all()
    )

    # Build price lookup: {(ticker_id, date): Decimal}
    price_map: dict[tuple[int, date], Decimal] = {}
    for p in prices_query:
        price_map[(p.ticker_id, p.date)] = p.close

    # Pre-seed LOCF: fetch the most recent close price BEFORE start for
    # each ticker so that single-day recomputes (e.g. from_date=today when
    # no DailyPrice exists yet for today) don't default to 0.
    last_known_price: dict[int, Decimal] = {}
    if all_ticker_ids:
        from sqlalchemy import func, and_

        # Subquery: latest date < start per ticker
        latest_sub = (
            db.session.query(
                DailyPrice.ticker_id,
                func.max(DailyPrice.date).label("max_date"),
            )
            .filter(
                DailyPrice.ticker_id.in_(all_ticker_ids),
                DailyPrice.date < start,
            )
            .group_by(DailyPrice.ticker_id)
            .subquery()
        )

        seed_prices = (
            db.session.query(DailyPrice.ticker_id, DailyPrice.close)
            .join(
                latest_sub,
                and_(
                    DailyPrice.ticker_id == latest_sub.c.ticker_id,
                    DailyPrice.date == latest_sub.c.max_date,
                ),
            )
            .all()
        )

        for tid, close in seed_prices:
            last_known_price[tid] = close

    # Iterate day by day
    current = start
    snapshots_to_upsert = []

    while current <= end:
        # Update last known prices (LOCF)
        for tid in all_ticker_ids:
            key = (tid, current)
            if key in price_map:
                last_known_price[tid] = price_map[key]

        # Compute holdings at this date
        total_value = Decimal(0)
        total_invested = Decimal(0)

        holdings: dict[int, dict] = defaultdict(lambda: {"qty": Decimal(0), "cost": Decimal(0)})
        for tx in transactions:
            if tx.date > current:
                break
            h = holdings[tx.ticker_id]
            if tx.type == "BUY":
                h["cost"] += tx.quantity * tx.price_per_share + tx.fees
                h["qty"] += tx.quantity
            elif tx.type == "SELL":
                if h["qty"] > 0:
                    pru = h["cost"] / h["qty"]
                    h["cost"] -= pru * tx.quantity
                    h["qty"] -= tx.quantity

        for tid, h in holdings.items():
            if h["qty"] > 0:
                total_invested += h["cost"]
                price = last_known_price.get(tid, Decimal(0))
                total_value += h["qty"] * price

        total_pnl = total_value - total_invested
        total_pnl_pct = ((total_value / total_invested) - 1) * 100 if total_invested > 0 else 0

        snapshots_to_upsert.append({
            "user_id": user_id,
            "date": current,
            "total_value": total_value,
            "total_invested": total_invested,
            "total_pnl": total_pnl,
            "total_pnl_pct": total_pnl_pct,
        })

        current += timedelta(days=1)

    # Bulk upsert snapshots
    for s in snapshots_to_upsert:
        existing = PortfolioSnapshot.query.filter_by(
            user_id=s["user_id"], date=s["date"]
        ).first()
        if existing:
            existing.total_value = s["total_value"]
            existing.total_invested = s["total_invested"]
            existing.total_pnl = s["total_pnl"]
            existing.total_pnl_pct = s["total_pnl_pct"]
        else:
            db.session.add(PortfolioSnapshot(**s))

    db.session.commit()
    logger.info("Computed %d snapshots for user %d", len(snapshots_to_upsert), user_id)


def ensure_snapshots_uptodate(user_id: int):
    """
    Ensure portfolio snapshots are complete from first transaction to today.

    - Detects *all* missing days (gaps in the middle) and fills them.
    - Always recomputes today so the latest prices are reflected.
    - Does NOT use an arbitrary time window — transaction additions and
      deletions already trigger compute_snapshots from the relevant date,
      so this function only needs to handle gaps + today.

    Safe to call frequently — minimal work when everything is up-to-date.
    """
    first_tx = (
        Transaction.query.filter_by(user_id=user_id)
        .order_by(Transaction.date)
        .first()
    )
    if not first_tx:
        return

    first_date = first_tx.date
    today = date.today()
    if first_date > today:
        return

    # All existing snapshot dates for this user
    existing_dates = set(
        row[0]
        for row in db.session.query(PortfolioSnapshot.date)
        .filter_by(user_id=user_id)
        .filter(PortfolioSnapshot.date >= first_date)
        .filter(PortfolioSnapshot.date <= today)
        .all()
    )

    # Build the full expected set of dates
    expected_dates: set[date] = set()
    current = first_date
    while current <= today:
        expected_dates.add(current)
        current += timedelta(days=1)

    missing = expected_dates - existing_dates

    if missing:
        earliest_missing = min(missing)
        logger.info(
            "Found %d missing snapshot(s) for user %d — earliest gap: %s. Recomputing…",
            len(missing), user_id, earliest_missing,
        )
        compute_snapshots(user_id, from_date=earliest_missing)
    elif today not in existing_dates:
        # Refresh today only if snapshot is genuinely missing
        compute_snapshots(user_id, from_date=today)


def get_snapshot_series(user_id: int, period: str = "1Y") -> list[dict]:
    """Return portfolio snapshot series for charting."""
    period_map = {
        "1M": 30, "3M": 90, "6M": 180, "1Y": 365, "MAX": 9999
    }
    days = period_map.get(period, 365)
    start = date.today() - timedelta(days=days)

    snapshots = (
        PortfolioSnapshot.query
        .filter_by(user_id=user_id)
        .filter(PortfolioSnapshot.date >= start)
        .order_by(PortfolioSnapshot.date)
        .all()
    )

    return [
        {
            "date": s.date.isoformat(),
            "value": float(round(s.total_value, 2)),
            "invested": float(round(s.total_invested, 2)),
            "pnl": float(round(s.total_pnl, 2)),
            "pnl_pct": float(round(s.total_pnl_pct, 2)),
        }
        for s in snapshots
    ]
