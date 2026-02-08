from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from app.extensions import db, limiter
from app.models import User

from .forms import LoginForm, RegisterForm

auth_bp = Blueprint("auth", __name__, template_folder="../templates/auth")


@auth_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute")
def login():
    if current_user.is_authenticated:
        return redirect(url_for("portfolio.dashboard"))

    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.lower().strip()).first()
        if user and user.check_password(form.password.data):
            login_user(user, remember=True)
            next_page = request.args.get("next")
            return redirect(next_page or url_for("portfolio.dashboard"))
        flash("Email ou mot de passe incorrect.", "error")

    return render_template("login.html", form=form)


@auth_bp.route("/register", methods=["GET", "POST"])
@limiter.limit("5 per minute")
def register():
    if current_user.is_authenticated:
        return redirect(url_for("portfolio.dashboard"))

    form = RegisterForm()
    if form.validate_on_submit():
        existing = User.query.filter_by(email=form.email.data.lower().strip()).first()
        if existing:
            flash("Un compte existe déjà avec cet email.", "error")
            return render_template("register.html", form=form)

        user = User(email=form.email.data.lower().strip())
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        login_user(user)
        flash("Compte créé avec succès ! Commencez par ajouter vos transactions.", "success")
        return redirect(url_for("portfolio.transactions"))

    return render_template("register.html", form=form)


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))
