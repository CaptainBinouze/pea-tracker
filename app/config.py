import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", "sqlite:///pea_tracker.db"
    )
    # Railway uses postgres:// but SQLAlchemy needs postgresql://
    if SQLALCHEMY_DATABASE_URI.startswith("postgres://"):
        SQLALCHEMY_DATABASE_URI = SQLALCHEMY_DATABASE_URI.replace(
            "postgres://", "postgresql://", 1
        )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_TIME_LIMIT = None  # No CSRF token expiry

    # Intraday live quotes (APScheduler)
    ENABLE_INTRADAY = os.environ.get("ENABLE_INTRADAY", "false").lower() in ("1", "true", "yes")
    INTRADAY_INTERVAL_MINUTES = int(os.environ.get("INTRADAY_INTERVAL_MINUTES", "10"))
    MARKET_OPEN_HOUR = float(os.environ.get("MARKET_OPEN_HOUR", "9"))       # CET
    MARKET_CLOSE_HOUR = float(os.environ.get("MARKET_CLOSE_HOUR", "17.5"))  # CET (17:30)
