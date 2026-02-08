from flask_wtf import FlaskForm
from wtforms import FloatField, SelectField, StringField, SubmitField
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
    threshold_price = FloatField(
        "Prix seuil (€)",
        validators=[DataRequired(), NumberRange(min=0.01)],
    )
    submit = SubmitField("Créer l'alerte")
