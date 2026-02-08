from flask_wtf import FlaskForm
from wtforms import EmailField, PasswordField, SubmitField
from wtforms.validators import DataRequired, Email, EqualTo, Length


class LoginForm(FlaskForm):
    email = EmailField("Email", validators=[DataRequired(), Email()])
    password = PasswordField("Mot de passe", validators=[DataRequired()])
    submit = SubmitField("Se connecter")


class RegisterForm(FlaskForm):
    email = EmailField("Email", validators=[DataRequired(), Email()])
    password = PasswordField(
        "Mot de passe", validators=[DataRequired(), Length(min=8, message="8 caractères minimum")]
    )
    password_confirm = PasswordField(
        "Confirmer le mot de passe",
        validators=[DataRequired(), EqualTo("password", message="Les mots de passe ne correspondent pas")],
    )
    submit = SubmitField("Créer un compte")
