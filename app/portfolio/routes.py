import threading
from datetime import date as date_type
from decimal import Decimal

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func as sqlfunc

from app.extensions import db
from app.market.services import get_or_create_ticker, process_backfill_queue, request_backfill
from app.models import BackfillQueue, DailyPrice, Dividend, PortfolioSnapshot, Ticker, Transaction
from app.portfolio.forms import TransactionForm
from app.portfolio.services import (
    compute_snapshots,
    ensure_snapshots_uptodate,
    get_portfolio_summary,
    get_positions,
    get_snapshot_series,
)

portfolio_bp = Blueprint(
    "portfolio", __name__, url_prefix="/portfolio", template_folder="../templates/portfolio"
)


# ---------------------------------------------------------------------------
# Background workers
# ---------------------------------------------------------------------------

def _background_add(app, ticker_id, tx_date, user_id):
    """Run backfill + snapshot computation in a background thread."""
    with app.app_context():
        try:
            request_backfill(ticker_id, tx_date)
            process_backfill_queue()
            compute_snapshots(user_id, from_date=tx_date)
        except Exception as e:
            app.logger.error(f"[background_add] Error: {e}")


def _background_delete(app, user_id, tx_date):
    """Recompute snapshots after deletion in a background thread."""
    with app.app_context():
        try:
            compute_snapshots(user_id, from_date=tx_date)
        except Exception as e:
            app.logger.error(f"[background_delete] Error: {e}")


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@portfolio_bp.route("/dashboard")
@login_required
def dashboard():
    summary = get_portfolio_summary(current_user.id)

    # Check if backfill is needed and auto-trigger
    backfill_ran = False
    pending = BackfillQueue.query.filter_by(status="PENDING").count()
    if pending > 0:
        result = process_backfill_queue()
        backfill_ran = result.get("processed", 0) > 0

    # Ensure all snapshots are complete and fresh
    if summary["num_positions"] > 0:
        if backfill_ran:
            # New price data just arrived — force full recompute so snapshots
            # that were previously calculated with missing prices get corrected.
            compute_snapshots(current_user.id)
        else:
            ensure_snapshots_uptodate(current_user.id)
        summary = get_portfolio_summary(current_user.id)

    series = get_snapshot_series(current_user.id, request.args.get("period", "1Y"))

    # Prepare JSON-serializable position data for the allocation chart
    chart_positions = [
        {"symbol": p["ticker"].symbol, "weight": float(p["weight"])}
        for p in summary["positions"]
    ]

    return render_template(
        "dashboard.html",
        summary=summary,
        series=series,
        period=request.args.get("period", "1Y"),
        chart_positions=chart_positions,
    )


@portfolio_bp.route("/dashboard/positions")
@login_required
def dashboard_positions():
    """HTMX partial — positions table."""
    positions = get_positions(current_user.id)
    return render_template("partials/positions_table.html", positions=positions)


@portfolio_bp.route("/dashboard/chart")
@login_required
def dashboard_chart():
    """HTMX partial — portfolio evolution chart data."""
    period = request.args.get("period", "1Y")
    series = get_snapshot_series(current_user.id, period)
    return render_template("partials/portfolio_chart.html", series=series, period=period)


@portfolio_bp.route("/dashboard/summary")
@login_required
def dashboard_summary():
    """HTMX partial — summary cards."""
    summary = get_portfolio_summary(current_user.id)
    return render_template("partials/summary_cards.html", summary=summary)


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------

@portfolio_bp.route("/transactions")
@login_required
def transactions():
    page = request.args.get("page", 1, type=int)
    txns = (
        Transaction.query
        .filter_by(user_id=current_user.id)
        .order_by(Transaction.date.desc())
        .paginate(page=page, per_page=20)
    )
    form = TransactionForm()
    return render_template("transactions.html", transactions=txns, form=form)


@portfolio_bp.route("/transactions/add", methods=["POST"])
@login_required
def add_transaction():
    form = TransactionForm()
    if form.validate_on_submit():
        # Get or create ticker
        ticker = get_or_create_ticker(form.ticker_symbol.data)

        # Validate sell quantity
        if form.type.data == "SELL":
            held = _quantity_held(current_user.id, ticker.id)
            if form.quantity.data > held:
                flash(f"Vous ne détenez que {held:.4f} actions de {ticker.symbol}.", "error")
                return redirect(url_for("portfolio.transactions"))

        tx = Transaction(
            user_id=current_user.id,
            ticker_id=ticker.id,
            type=form.type.data,
            quantity=form.quantity.data,
            price_per_share=form.price_per_share.data,
            fees=form.fees.data or Decimal(0),
            date=form.date.data,
            notes=form.notes.data,
        )
        db.session.add(tx)
        db.session.commit()

        # Run heavy operations (backfill + snapshots) in a background thread
        app = current_app._get_current_object()
        threading.Thread(
            target=_background_add,
            args=(app, ticker.id, form.date.data, current_user.id),
            daemon=True,
        ).start()

        flash(
            f"Transaction {'achat' if tx.type == 'BUY' else 'vente'} de {ticker.symbol} enregistrée. "
            "Les données du portfolio se mettent à jour en arrière-plan.",
            "success",
        )
        return redirect(url_for("portfolio.transactions"))

    for field, errors in form.errors.items():
        for error in errors:
            flash(f"{error}", "error")
    return redirect(url_for("portfolio.transactions"))


@portfolio_bp.route("/transactions/<int:tx_id>/delete", methods=["POST"])
@login_required
def delete_transaction(tx_id):
    tx = Transaction.query.filter_by(id=tx_id, user_id=current_user.id).first_or_404()
    tx_date = tx.date
    db.session.delete(tx)
    db.session.commit()

    # Recompute snapshots in background
    app = current_app._get_current_object()
    threading.Thread(
        target=_background_delete,
        args=(app, current_user.id, tx_date),
        daemon=True,
    ).start()

    flash("Transaction supprimée.", "success")

    # If HTMX request, return updated table
    if request.headers.get("HX-Request"):
        page = request.args.get("page", 1, type=int)
        txns = (
            Transaction.query
            .filter_by(user_id=current_user.id)
            .order_by(Transaction.date.desc())
            .paginate(page=page, per_page=20)
        )
        return render_template("partials/transactions_list.html", transactions=txns)

    return redirect(url_for("portfolio.transactions"))


# ---------------------------------------------------------------------------
# Position detail
# ---------------------------------------------------------------------------

@portfolio_bp.route("/position/<string:symbol>")
@login_required
def position_detail(symbol):
    ticker = Ticker.query.filter_by(symbol=symbol.upper()).first_or_404()
    positions = get_positions(current_user.id)
    position = next((p for p in positions if p["ticker"].id == ticker.id), None)

    if not position:
        flash("Vous ne détenez pas cette action.", "error")
        return redirect(url_for("portfolio.dashboard"))

    # Get price history for chart
    prices = (
        DailyPrice.query.filter_by(ticker_id=ticker.id)
        .order_by(DailyPrice.date)
        .all()
    )
    price_data = [
        {
            "time": p.date.isoformat(),
            "open": float(p.open),
            "high": float(p.high),
            "low": float(p.low),
            "close": float(p.close),
        }
        for p in prices
        if p.open and p.high and p.low and p.close
    ]

    # Get transactions for this ticker
    txns = (
        Transaction.query
        .filter_by(user_id=current_user.id, ticker_id=ticker.id)
        .order_by(Transaction.date.desc())
        .all()
    )

    # Get dividends
    dividends = (
        Dividend.query.filter_by(ticker_id=ticker.id)
        .order_by(Dividend.date.desc())
        .all()
    )

    return render_template(
        "position_detail.html",
        ticker=ticker,
        position=position,
        price_data=price_data,
        transactions=txns,
        dividends=dividends,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _quantity_held(user_id: int, ticker_id: int) -> float:
    result = (
        db.session.query(
            sqlfunc.coalesce(
                sqlfunc.sum(
                    db.case(
                        (Transaction.type == "BUY", Transaction.quantity),
                        else_=-Transaction.quantity,
                    )
                ),
                0,
            )
        )
        .filter(
            Transaction.user_id == user_id,
            Transaction.ticker_id == ticker_id,
        )
        .scalar()
    )
    return float(result)
