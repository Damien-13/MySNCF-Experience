"""Connexion à la base de données.

L'URL est dans .env : DATABASE_URL=sqlite:///data/mysncf.db  ou  postgresql+psycopg://user:mdp@localhost/mysncf
"""
import os

from dotenv import load_dotenv
from sqlalchemy import create_engine

load_dotenv()


def get_engine():
    """Moteur SQLAlchemy construit depuis DATABASE_URL."""
    return create_engine(os.environ["DATABASE_URL"])
