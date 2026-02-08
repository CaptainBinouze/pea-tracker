from datetime import date, datetime

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------
class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    transactions = db.relationship("Transaction", back_populates="user", lazy="dynamic")
    snapshots = db.relationship("PortfolioSnapshot", back_populates="user", lazy="dynamic")
    alerts = db.relationship("Alert", back_populates="user", lazy="dynamic")
    notification_preference = db.relationship(
        "NotificationPreference", back_populates="user", uselist=False
    )

    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


# ---------------------------------------------------------------------------
# Ticker (shared across all users)
# ---------------------------------------------------------------------------
class Ticker(db.Model):
    __tablename__ = "tickers"

    id = db.Column(db.Integer, primary_key=True)
    symbol = db.Column(db.String(20), unique=True, nullable=False, index=True)
    name = db.Column(db.String(255))
    exchange = db.Column(db.String(50))
    currency = db.Column(db.String(10), default="EUR")
    sector = db.Column(db.String(100))
    last_updated = db.Column(db.DateTime)

    daily_prices = db.relationship("DailyPrice", back_populates="ticker", lazy="dynamic")
    dividends = db.relationship("Dividend", back_populates="ticker", lazy="dynamic")
    transactions = db.relationship("Transaction", back_populates="ticker", lazy="dynamic")

    def __repr__(self):
        return f"<Ticker {self.symbol}>"


# ---------------------------------------------------------------------------
# Transaction (buy / sell)
# ---------------------------------------------------------------------------
class Transaction(db.Model):
    __tablename__ = "transactions"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    ticker_id = db.Column(db.Integer, db.ForeignKey("tickers.id"), nullable=False, index=True)
    type = db.Column(db.String(4), nullable=False)  # BUY or SELL
    quantity = db.Column(db.Float, nullable=False)
    price_per_share = db.Column(db.Float, nullable=False)
    fees = db.Column(db.Float, default=0.0)
    date = db.Column(db.Date, nullable=False)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User", back_populates="transactions")
    ticker = db.relationship("Ticker", back_populates="transactions")

    @property
    def total_cost(self) -> float:
        """Total cost including fees."""
        if self.type == "BUY":
            return self.quantity * self.price_per_share + self.fees
        return self.quantity * self.price_per_share - self.fees


# ---------------------------------------------------------------------------
# Daily Price (OHLCV — shared across users)
# ---------------------------------------------------------------------------
class DailyPrice(db.Model):
    __tablename__ = "daily_prices"
    __table_args__ = (
        db.UniqueConstraint("ticker_id", "date", name="uq_daily_price_ticker_date"),
    )

    id = db.Column(db.Integer, primary_key=True)
    ticker_id = db.Column(db.Integer, db.ForeignKey("tickers.id"), nullable=False, index=True)
    date = db.Column(db.Date, nullable=False, index=True)
    open = db.Column(db.Float)
    high = db.Column(db.Float)
    low = db.Column(db.Float)
    close = db.Column(db.Float)
    volume = db.Column(db.BigInteger)

    ticker = db.relationship("Ticker", back_populates="daily_prices")


# ---------------------------------------------------------------------------
# Dividend
# ---------------------------------------------------------------------------
class Dividend(db.Model):
    __tablename__ = "dividends"
    __table_args__ = (
        db.UniqueConstraint("ticker_id", "date", name="uq_dividend_ticker_date"),
    )

    id = db.Column(db.Integer, primary_key=True)
    ticker_id = db.Column(db.Integer, db.ForeignKey("tickers.id"), nullable=False, index=True)
    date = db.Column(db.Date, nullable=False)
    amount_per_share = db.Column(db.Float, nullable=False)

    ticker = db.relationship("Ticker", back_populates="dividends")


# ---------------------------------------------------------------------------
# Portfolio Snapshot (daily valuation per user)
# ---------------------------------------------------------------------------
class PortfolioSnapshot(db.Model):
    __tablename__ = "portfolio_snapshots"
    __table_args__ = (
        db.UniqueConstraint("user_id", "date", name="uq_snapshot_user_date"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    date = db.Column(db.Date, nullable=False)
    total_value = db.Column(db.Float, default=0.0)
    total_invested = db.Column(db.Float, default=0.0)
    total_pnl = db.Column(db.Float, default=0.0)
    total_pnl_pct = db.Column(db.Float, default=0.0)

    user = db.relationship("User", back_populates="snapshots")


# ---------------------------------------------------------------------------
# Alert
# ---------------------------------------------------------------------------
class Alert(db.Model):
    __tablename__ = "alerts"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    ticker_id = db.Column(db.Integer, db.ForeignKey("tickers.id"), nullable=False)
    condition = db.Column(db.String(10), nullable=False)  # ABOVE or BELOW
    threshold_price = db.Column(db.Float, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    triggered = db.Column(db.Boolean, default=False)
    last_triggered_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User", back_populates="alerts")
    ticker = db.relationship("Ticker")


# ---------------------------------------------------------------------------
# Notification Preference
# ---------------------------------------------------------------------------
class NotificationPreference(db.Model):
    __tablename__ = "notification_preferences"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False, unique=True, index=True
    )
    slack_enabled = db.Column(db.Boolean, default=False)
    slack_webhook_url = db.Column(db.String(500))

    user = db.relationship("User", back_populates="notification_preference")


# ---------------------------------------------------------------------------
# Backfill Queue
# ---------------------------------------------------------------------------
class BackfillQueue(db.Model):
    __tablename__ = "backfill_queue"

    id = db.Column(db.Integer, primary_key=True)
    ticker_id = db.Column(db.Integer, db.ForeignKey("tickers.id"), nullable=False)
    from_date = db.Column(db.Date, nullable=False)
    requested_at = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default="PENDING")  # PENDING, PROCESSING, DONE, FAILED
    error_message = db.Column(db.Text)

    ticker = db.relationship("Ticker")
