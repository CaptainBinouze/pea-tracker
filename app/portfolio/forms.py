from decimal import Decimal

from flask_wtf import FlaskForm
from wtforms import (
    DateField,
    DecimalField,
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
    quantity = DecimalField(
        "Quantité",
        places=4,
        validators=[DataRequired(), NumberRange(min=Decimal("0.0001"), message="Quantité positive requise")],
    )
    price_per_share = DecimalField(
        "Prix par action (€)",
        places=4,
        validators=[DataRequired(), NumberRange(min=Decimal("0.0001"))],
    )
    fees = DecimalField("Frais (€)", places=4, default=Decimal("0"), validators=[Optional(), NumberRange(min=0)])
    notes = TextAreaField("Notes", validators=[Optional()])
    submit = SubmitField("Enregistrer")
