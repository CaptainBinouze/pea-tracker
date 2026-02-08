from flask_wtf import FlaskForm
from wtforms import BooleanField, StringField, SubmitField
from wtforms.validators import Optional, URL


class NotificationPreferenceForm(FlaskForm):
    slack_enabled = BooleanField("Activer les notifications Slack")
    slack_webhook_url = StringField(
        "Webhook URL Slack",
        validators=[Optional(), URL(message="URL invalide")],
        render_kw={"placeholder": "https://hooks.slack.com/services/..."},
    )
    submit = SubmitField("Enregistrer")
