"""Écriture dans la base : insert, update, delete. Chaque appel est une transaction (tout passe ou rien).

Usage :
    insert(Lieu, df)                                  # DataFrame ou liste de dicts
    update(Lieu, {"commune": "Toulon"}, {"id": 12})   # valeurs à changer, filtre
    delete(Lieu, {"source": "basilic"})
Le filtre est une égalité colonne = valeur (plusieurs colonnes = ET). Il est obligatoire : pas de suppression ni de mise à jour de toute la table par accident.
"""
import pandas as pd
import sqlalchemy as sa

from lib.db.connection import get_engine

CHUNK_SIZE = 10_000


def _records(model, rows):
    """Liste de dicts prête à insérer : colonnes du modèle seulement, NaN → None, dates Python pour les colonnes Date."""
    if isinstance(rows, pd.DataFrame):
        cols = [c.name for c in model.__table__.columns if c.name in rows.columns]
        df = rows[cols].copy()
        for c in cols:
            if isinstance(model.__table__.columns[c].type, sa.Date):
                df[c] = pd.to_datetime(df[c], errors="coerce").dt.date
        return df.astype(object).where(df.notna(), None).to_dict("records")
    return list(rows)


def _filter(model, where):
    if not where:
        raise ValueError("un filtre est obligatoire (ex. {'id': 12})")
    return [model.__table__.columns[k] == v for k, v in where.items()]


def insert(model, rows):
    """Ajoute des lignes (DataFrame ou liste de dicts), par paquets. Retourne le nombre de lignes ajoutées."""
    records = _records(model, rows)
    with get_engine().begin() as conn:
        for i in range(0, len(records), CHUNK_SIZE):
            conn.execute(sa.insert(model), records[i:i + CHUNK_SIZE])
    return len(records)


def update(model, values, where):
    """Change les champs `values` des lignes qui correspondent à `where`. Retourne le nombre de lignes modifiées."""
    with get_engine().begin() as conn:
        return conn.execute(sa.update(model).where(*_filter(model, where)).values(**values)).rowcount


def delete(model, where):
    """Supprime les lignes qui correspondent à `where`. Retourne le nombre de lignes supprimées."""
    with get_engine().begin() as conn:
        return conn.execute(sa.delete(model).where(*_filter(model, where))).rowcount
