from flask import Blueprint, render_template, request
from flask_login import login_required

from app.market.services import process_backfill_queue, search_tickers
from app.models import BackfillQueue

market_bp = Blueprint("market", __name__, url_prefix="/market", template_folder="../templates/market")


@market_bp.route("/search")
@login_required
def search():
    """HTMX endpoint — returns ticker search results as HTML options."""
    q = request.args.get("q", "").strip()
    if len(q) < 2:
        return ""

    results = search_tickers(q)
    return render_template("partials/ticker_results.html", results=results, query=q)


@market_bp.route("/backfill", methods=["POST"])
@login_required
def trigger_backfill():
    """HTMX endpoint — triggers backfill processing and returns status."""
    result = process_backfill_queue()
    return render_template("partials/backfill_status.html", result=result, done=True)


@market_bp.route("/backfill/status")
@login_required
def backfill_status():
    """HTMX polling endpoint — returns current backfill status."""
    pending = BackfillQueue.query.filter_by(status="PENDING").count()
    processing = BackfillQueue.query.filter_by(status="PROCESSING").count()
    failed = BackfillQueue.query.filter(BackfillQueue.status == "FAILED").all()

    return render_template(
        "partials/backfill_status.html",
        pending=pending,
        processing=processing,
        failed=failed,
        done=(pending == 0 and processing == 0),
    )
