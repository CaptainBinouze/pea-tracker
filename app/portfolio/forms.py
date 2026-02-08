from flask_wtf import FlaskForm
from wtforms import (
    DateField,
    FloatField,
    HiddenField,
    SelectField,
    StringField,
    SubmitField,
    TextAreaField,
)
from wtforms.validators import DataRequired, NumberRange, Optional


class TransactionForm(FlaskForm):
    ticker_symbol = StringField(
        "Ticker",
        validators=[DataRequired(message="Sélectionnez un ticker")],
        render_kw={"placeholder": "Rechercher (ex: TTE.PA, CW8...)"},
    )
    ticker_name = HiddenField()
    type = SelectField(
        "Type",
        choices=[("BUY", "Achat"), ("SELL", "Vente")],
        validators=[DataRequired()],
    )
    date = DateField("Date", validators=[DataRequired()])
    quantity = FloatField(
        "Quantité",
        validators=[DataRequired(), NumberRange(min=0.0001, message="Quantité positive requise")],
    )
    price_per_share = FloatField(
        "Prix par action (€)",
        validators=[DataRequired(), NumberRange(min=0.01)],
    )
    fees = FloatField("Frais (€)", default=0.0, validators=[Optional(), NumberRange(min=0)])
    notes = TextAreaField("Notes", validators=[Optional()])
    submit = SubmitField("Enregistrer")
