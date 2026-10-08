# MySNCF-Experience

Description du projet à compléter.

## Structure

```
src/        code source de l'application
data/       données (non versionnées)
lib/        bibliothèques et modules réutilisables (téléchargement ; lib/db : connexion et modèles de la base)
migrations/ migrations de la base de données (Alembic)
```

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Configuration

Copier `.env.example` en `.env` puis renseigner les variables.

## Extraction des données

Déclarer chaque lien dans `.env` (`DATASET_<SOURCE>_URL=...`), puis :

```bash
python -c "from lib.downloader import download; download(['basilic'])"
```

Chaque lien est téléchargé dans `data/<source>/` (les `.zip` sont décompressés).

## Base de données

Les tables sont décrites dans `lib/db/models.py` (SQLAlchemy). L'URL de la base est `DATABASE_URL` dans `.env`
(SQLite par défaut, PostgreSQL possible en changeant l'URL).

```bash
python migrations/migration.py                         # applique les migrations de migrations/versions/ jusqu'à la plus récente
python migrations/migration.py --new "ajoute X"   # après avoir modifié lib/db/models.py : crée la migration suivante (002, 003…)
```

Une migration existante ne se modifie jamais : toute évolution du schéma est une nouvelle migration, à relire avant de l'appliquer.

## Licence

Voir [LICENSE](LICENSE).
