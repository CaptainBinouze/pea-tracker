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

def get_positions(user_id: int) -> list[dict]:
    """
    Compute current positions for a user.
    Returns list of dicts with: ticker info, quantity, PRU, current price, P&L, weight.
    """
    transactions = (
        Transaction.query.filter_by(user_id=user_id)
        .order_by(Transaction.date)
        .all()
    )

    # Aggregate by ticker
    holdings: dict[int, dict] = defaultdict(lambda: {
        "qty": Decimal(0),
        "total_cost": Decimal(0),
        "total_sold": Decimal(0),
        "realized_pnl": Decimal(0),
    })

    for tx in transactions:
        h = holdings[tx.ticker_id]
        if tx.type == "BUY":
            h["total_cost"] += tx.quantity * tx.price_per_share + tx.fees
            h["qty"] += tx.quantity
        elif tx.type == "SELL":
            if h["qty"] > 0:
                pru = h["total_cost"] / h["qty"] if h["qty"] else 0
                h["realized_pnl"] += (tx.price_per_share - pru) * tx.quantity - tx.fees
                h["total_cost"] -= pru * tx.quantity
                h["qty"] -= tx.quantity

    # Build position list with current prices
    positions = []
    total_portfolio_value = Decimal(0)

    for ticker_id, h in holdings.items():
        if h["qty"] <= Decimal("0.0001"):
            continue

        ticker = db.session.get(Ticker, ticker_id)
        if not ticker:
            continue

        # Get latest price
        latest_price_row = (
            DailyPrice.query.filter_by(ticker_id=ticker_id)
            .order_by(DailyPrice.date.desc())
            .first()
        )
        current_price = latest_price_row.close if latest_price_row else None
        price_date = latest_price_row.date if latest_price_row else None

        # Get previous close for daily change
        prev_price_row = (
            DailyPrice.query.filter_by(ticker_id=ticker_id)
            .filter(DailyPrice.date < price_date)
            .order_by(DailyPrice.date.desc())
            .first()
        ) if price_date else None
        prev_close = prev_price_row.close if prev_price_row else current_price

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
    """Compute portfolio-level summary metrics."""
    positions = get_positions(user_id)

    total_value = sum(p["market_value"] for p in positions)
    total_invested = sum(p["invested"] for p in positions)
    total_unrealized = sum(p["unrealized_pnl"] for p in positions)
    total_realized = sum(p["realized_pnl"] for p in positions)
    total_pnl_pct = ((total_value / total_invested) - 1) * 100 if total_invested > 0 else 0

    # Total dividends received
    ticker_ids = [p["ticker"].id for p in positions]
    total_dividends = _compute_total_dividends(user_id, ticker_ids)

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


def _compute_total_dividends(user_id: int, ticker_ids: list[int]) -> float:
    """Compute total dividends received based on holdings at each ex-date."""
    if not ticker_ids:
        return 0.0

    total = 0.0
    dividends = Dividend.query.filter(Dividend.ticker_id.in_(ticker_ids)).all()

    for div in dividends:
        qty_at_date = (
            db.session.query(func.coalesce(func.sum(
                db.case(
                    (Transaction.type == "BUY", Transaction.quantity),
                    else_=-Transaction.quantity,
                )
            ), 0))
            .filter(
                Transaction.user_id == user_id,
                Transaction.ticker_id == div.ticker_id,
                Transaction.date <= div.date,
            )
            .scalar()
        )
        if qty_at_date > 0:
            total += qty_at_date * div.amount_per_share

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

    # Build price lookup: {(ticker_id, date): close}
    price_map: dict[tuple[int, date], float] = {}
    for p in prices_query:
        price_map[(p.ticker_id, p.date)] = p.close

    # Pre-seed LOCF: fetch the most recent close price BEFORE start for
    # each ticker so that single-day recomputes (e.g. from_date=today when
    # no DailyPrice exists yet for today) don't default to 0.
    last_known_price: dict[int, float] = {}
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
        total_value = 0.0
        total_invested = 0.0

        holdings: dict[int, dict] = defaultdict(lambda: {"qty": 0.0, "cost": 0.0})
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
                price = last_known_price.get(tid, 0)
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
    elif today not in existing_dates or True:
        # Always refresh today to pick up latest prices from cron / backfill
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
            "value": round(s.total_value, 2),
            "invested": round(s.total_invested, 2),
            "pnl": round(s.total_pnl, 2),
            "pnl_pct": round(s.total_pnl_pct, 2),
        }
        for s in snapshots
    ]
