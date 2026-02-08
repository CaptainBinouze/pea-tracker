from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.market.services import get_or_create_ticker
from app.models import Alert, DailyPrice

from .forms import AlertForm

alerts_bp = Blueprint("alerts", __name__, url_prefix="/alerts", template_folder="../templates/alerts")


@alerts_bp.route("/")
@login_required
def list_alerts():
    active = (
        Alert.query.filter_by(user_id=current_user.id, is_active=True, triggered=False)
        .order_by(Alert.created_at.desc())
        .all()
    )
    triggered = (
        Alert.query.filter_by(user_id=current_user.id, triggered=True)
        .order_by(Alert.last_triggered_at.desc())
        .limit(20)
        .all()
    )
    form = AlertForm()

    # Enrich with current prices
    for alert in active + triggered:
        latest = (
            DailyPrice.query.filter_by(ticker_id=alert.ticker_id)
            .order_by(DailyPrice.date.desc())
            .first()
        )
        alert.current_price = latest.close if latest else None

    return render_template("alerts.html", active=active, triggered=triggered, form=form)


@alerts_bp.route("/add", methods=["POST"])
@login_required
def add_alert():
    form = AlertForm()
    if form.validate_on_submit():
        ticker = get_or_create_ticker(form.ticker_symbol.data)
        alert = Alert(
            user_id=current_user.id,
            ticker_id=ticker.id,
            condition=form.condition.data,
            threshold_price=form.threshold_price.data,
        )
        db.session.add(alert)
        db.session.commit()

        condition_label = "au-dessus" if alert.condition == "ABOVE" else "en-dessous"
        flash(
            f"Alerte créée : {ticker.symbol} {condition_label} de {alert.threshold_price:.2f} €",
            "success",
        )
        return redirect(url_for("alerts.list_alerts"))

    for field, errors in form.errors.items():
        for error in errors:
            flash(error, "error")
    return redirect(url_for("alerts.list_alerts"))


@alerts_bp.route("/<int:alert_id>/delete", methods=["POST"])
@login_required
def delete_alert(alert_id):
    alert = Alert.query.filter_by(id=alert_id, user_id=current_user.id).first_or_404()
    db.session.delete(alert)
    db.session.commit()
    flash("Alerte supprimée.", "success")

    if request.headers.get("HX-Request"):
        active = Alert.query.filter_by(user_id=current_user.id, is_active=True, triggered=False).all()
        for a in active:
            latest = DailyPrice.query.filter_by(ticker_id=a.ticker_id).order_by(DailyPrice.date.desc()).first()
            a.current_price = latest.close if latest else None
        return render_template("partials/alerts_list.html", alerts=active)

    return redirect(url_for("alerts.list_alerts"))


@alerts_bp.route("/<int:alert_id>/reset", methods=["POST"])
@login_required
def reset_alert(alert_id):
    """Re-activate a triggered alert."""
    alert = Alert.query.filter_by(id=alert_id, user_id=current_user.id).first_or_404()
    alert.triggered = False
    alert.last_triggered_at = None
    db.session.commit()
    flash("Alerte réactivée.", "success")
    return redirect(url_for("alerts.list_alerts"))
