from decimal import Decimal

from flask_wtf import FlaskForm
from wtforms import DecimalField, SelectField, StringField, SubmitField
from wtforms.validators import DataRequired, NumberRange


class AlertForm(FlaskForm):
    ticker_symbol = StringField(
        "Ticker",
        validators=[DataRequired(message="Sélectionnez un ticker")],
        render_kw={"placeholder": "Rechercher (ex: TTE.PA)"},
    )
    condition = SelectField(
        "Condition",
        choices=[("ABOVE", "Au-dessus de"), ("BELOW", "En-dessous de")],
        validators=[DataRequired()],
    )
    threshold_price = DecimalField(
        "Prix seuil (€)",
        places=4,
        validators=[DataRequired(), NumberRange(min=Decimal("0.0001"))],
    )
    submit = SubmitField("Créer l'alerte")
