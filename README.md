# MySNCF-Experience

Description du projet à compléter.

## Structure

```
src/        code source de l'application
data/       données (non versionnées)
lib/        bibliothèques et modules réutilisables
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

## Licence

Voir [LICENSE](LICENSE).
