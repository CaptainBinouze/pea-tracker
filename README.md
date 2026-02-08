# PEA Tracker 📈

Application de suivi d'investissements PEA (Plan d'Épargne en Actions) avec dashboard, graphiques, alertes et dividendes.

## Stack technique

- **Backend** : Flask 3.1 + SQLAlchemy + Flask-Login
- **Frontend** : HTMX 2.0 + Pico CSS v2 (server-rendered, pas de framework JS)
- **Graphiques** : Lightweight Charts (TradingView) + Chart.js
- **Données marché** : yfinance (cours OHLCV, dividendes)
- **Base de données** : PostgreSQL (prod) / SQLite (dev)
- **Déploiement** : Railway

## Fonctionnalités

- **Multi-utilisateur** avec authentification (email/mot de passe)
- **Transactions** : achat/vente avec date, prix, frais
- **Dashboard** : valeur totale, P&L réalisé/latent, évolution du portefeuille
- **Graphiques** : chandelier (par action), évolution du portefeuille, allocation (doughnut)
- **Alertes de prix** : notification quand un cours dépasse un seuil
- **Dividendes** : suivi automatique via yfinance
- **Backfill automatique** : ajout d'une transaction passée → récupération automatique des cours historiques
- **Cron job** : mise à jour quotidienne des cours à 18h CET

## Installation locale

### Prérequis
- Python 3.11+
- (Optionnel) PostgreSQL pour reproduire l'environnement de prod

### Setup

```bash
# Cloner le repo
git clone <url> pea-tracker
cd pea-tracker

# Créer un environnement virtuel
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows

# Installer les dépendances
pip install -r requirements.txt

# Configurer les variables d'environnement
cp .env.example .env
# Éditer .env avec votre SECRET_KEY

# Initialiser la base de données
flask db init
flask db migrate -m "initial"
flask db upgrade

# Lancer l'application
flask run
```

L'app est accessible sur http://localhost:5000

### Variables d'environnement

| Variable | Description | Défaut |
|----------|-------------|--------|
| `SECRET_KEY` | Clé secrète Flask | (obligatoire) |
| `DATABASE_URL` | URL PostgreSQL | `sqlite:///pea.db` |
| `FLASK_ENV` | `development` ou `production` | `production` |

## Déploiement Railway

1. Créer un nouveau projet sur [Railway](https://railway.app)
2. Ajouter un service PostgreSQL
3. Connecter le repo GitHub
4. Les variables `DATABASE_URL` et `PORT` sont automatiquement injectées
5. Ajouter `SECRET_KEY` dans les variables d'environnement
6. Le cron job est configuré dans `railway.toml`

### Cron job

Le fichier `railway.toml` configure un cron job qui s'exécute à 17h00 UTC (18h00 CET) les jours de bourse (lundi-vendredi) pour :
- Traiter la file d'attente de backfill
- Récupérer les cours du jour pour tous les tickers
- Récupérer les nouveaux dividendes
- Évaluer les alertes de prix

## Tickers supportés

Tous les tickers disponibles sur Yahoo Finance, notamment :
- **Actions Euronext Paris** : `TTE.PA`, `MC.PA`, `AI.PA`, `SAN.PA`...
- **ETF européens** : `CW8.PA` (Amundi MSCI World), `EWLD.PA`, `PANX.PA`...
- **ETF US** (si éligible PEA) : suffixe `.PA` pour les versions Euronext

## Structure du projet

```
pea-tracker/
├── app/
│   ├── __init__.py          # App factory
│   ├── config.py            # Configuration
│   ├── extensions.py        # Flask extensions
│   ├── models.py            # SQLAlchemy models
│   ├── auth/                # Authentication blueprint
│   ├── portfolio/           # Portfolio & transactions
│   ├── market/              # yfinance services & search
│   ├── alerts/              # Price alerts
│   ├── templates/           # Jinja2 templates
│   └── static/css/          # Custom CSS
├── jobs/
│   └── fetch_prices.py      # Cron job script
├── wsgi.py                  # WSGI entry point
├── Procfile                 # Railway web process
├── railway.toml             # Railway config + cron
├── requirements.txt         # Python dependencies
└── .env.example             # Environment template
```

## Licence

Projet personnel — usage privé.
