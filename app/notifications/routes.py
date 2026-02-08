from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models import NotificationPreference
from app.notifications import notifications_bp
from app.notifications.forms import NotificationPreferenceForm


@notifications_bp.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    pref = NotificationPreference.query.filter_by(user_id=current_user.id).first()

    if pref is None:
        pref = NotificationPreference(user_id=current_user.id)
        db.session.add(pref)
        db.session.commit()

    form = NotificationPreferenceForm(obj=pref)

    if form.validate_on_submit():
        pref.slack_enabled = form.slack_enabled.data
        pref.slack_webhook_url = form.slack_webhook_url.data or None
        db.session.commit()
        flash("Préférences de notification enregistrées.", "success")
        return redirect(url_for("notifications.settings"))

    return render_template("notifications/settings.html", form=form, pref=pref)
