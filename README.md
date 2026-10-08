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

## Initialisation

```bash
python src/initialize.py   # crée la base de données (SQLite par défaut), puis télécharge les données nécessaires
```

Relançable sans risque. Le téléchargement des données nécessaires reste à brancher (liste `SOURCES` dans `src/initialize.py`).

## Transformation

Nettoie les données de `data/` et les charge dans la base. Les flux temps réel (`FLUX_*`) n'y passent pas.

```bash
python src/transformation/transformation.py   # lance toutes les étapes dans l'ordre
```

Une étape par domaine, dans `src/transformation/` (nettoyage, transformation et chargement). Pour l'instant : `gare.py`
(gares_voyageurs + horaires_gares → tables `lieu`, `gare`, `gare_horaire`). Pour ajouter un domaine : créer son module
avec une fonction `transformer()`, puis l'ajouter à `ETAPES` dans `transformation.py`.

Relançable sans risque : les données de chaque source sont remplacées à chaque passage.

## Base de données

Les tables sont décrites dans `lib/db/models.py` (SQLAlchemy). L'URL de la base est `DATABASE_URL` dans `.env`
(SQLite par défaut, PostgreSQL possible en changeant l'URL).

```bash
python migrations/migration.py                         # applique les migrations de migrations/versions/ jusqu'à la plus récente
python migrations/migration.py --new "ajoute X"   # après avoir modifié lib/db/models.py : crée la migration suivante (002, 003…)
```

Une migration existante ne se modifie jamais : toute évolution du schéma est une nouvelle migration, à relire avant de l'appliquer.

## Schéma macro de la base de données

```text
  TRANSPORT                                    EMPLACEMENTS
  ┌─────────┐                                  ┌────────────────────────┐
  │ reseau  │                                  │         lieu           │
  └────┬────┘                                  │ type : gare, arret_bus,│
       │ 1-n                                   │ station_velo, culture… │
  ┌────┴────┐                                  │ lat, lon, adresse      │
  │ ligne   │                                  │ gare_proche → lieu     │
  └────┬────┘                                  │ distance_gare_km       │
       │ 1-n                                   └──┬──────┬──────┬───────┘
  ┌────┴────────┐   ┌────────────┐                │      │      │
  │ circulation ├───┤ calendrier │      ┌─────────┘      │      └──────────┐
  └────┬────────┘   └────────────┘      │ 1-1            │ 1-1             │ n-n
       │ 1-n                       ┌────┴────┐   ┌───────┴──────┐  ┌───────┴────────┐
  ┌────┴────┐      ┌───────┐  n-1  │  gare   │   │ station_velo │  │ evenement_lieu │
  │ passage ├─n-1──┤ arret ├──────►│ (lieu)  │   └──────────────┘  └───────┬────────┘
  └─────────┘      └───────┘       └────┬────┘                             │ n-1
                    un arrêt GTFS       │ 1-n                       ┌──────┴─────┐
                    pointe vers         ┌┴─────────────┐            │ evenement  │
                    son lieu            │ gare_horaire │            └──────┬─────┘
                                        └──────────────┘                   │ 1-n
                                                               ┌───────────┴───────┐
                                                               │ evenement_periode │
                                                               └───────────────────┘
```

## Licence

Voir [LICENSE](LICENSE).
