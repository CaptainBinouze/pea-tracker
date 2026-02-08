from flask import Flask

from app.config import Config
from app.extensions import csrf, db, limiter, login_manager, migrate


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Initialize extensions
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)

    # User loader for Flask-Login
    from app.models import User

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    # Register blueprints
    from app.auth.routes import auth_bp
    from app.portfolio.routes import portfolio_bp
    from app.market.routes import market_bp
    from app.alerts.routes import alerts_bp
    from app.notifications import notifications_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(portfolio_bp)
    app.register_blueprint(market_bp)
    app.register_blueprint(alerts_bp)
    app.register_blueprint(notifications_bp)

    # Root redirect
    @app.route("/")
    def index():
        from flask import redirect, url_for
        return redirect(url_for("portfolio.dashboard"))

    # Jinja2 helpers
    @app.template_filter("currency")
    def currency_filter(value):
        if value is None:
            return "—"
        return f"{value:,.2f} €".replace(",", " ")

    @app.template_filter("pct")
    def pct_filter(value):
        if value is None:
            return "—"
        sign = "+" if value > 0 else ""
        return f"{sign}{value:.2f} %"

    @app.template_filter("color")
    def color_filter(value):
        if value is None or value == 0:
            return ""
        return "positive" if value > 0 else "negative"

    @app.context_processor
    def inject_pending_backfills():
        from flask_login import current_user
        from app.models import BackfillQueue
        count = 0
        if current_user.is_authenticated:
            count = BackfillQueue.query.filter_by(status="PENDING").count()
        return dict(pending_backfills=count)

    return app
