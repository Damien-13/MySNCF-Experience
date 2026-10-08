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
python src/initialize.py   # crée la base (SQLite par défaut), télécharge les sources, puis les nettoie et les charge
```

Relançable sans risque : la base déjà à jour n'est pas modifiée, les sources déjà présentes dans `data/<source>/` ne sont pas
retéléchargées, et la transformation remplace les données de chaque source (environ 2 min 30 pour tout recharger).
Les sources à télécharger sont la liste `SOURCES` de `src/initialize.py` ; chacune doit avoir son `DATASET_<SOURCE>_URL` dans le `.env`.

## Flux temps réel

`lib/flux.py` lit les stations de vélos en libre-service déclarées en `FLUX_<NOM>_URL` dans le `.env` (GBFS v2 et v3). C'est le dashboard
qui l'appelle à chaque actualisation : rien n'est stocké en base, et la transformation n'y touche pas.

```python
from lib.flux import lire, lire_tous
stations, erreurs = lire_tous()   # une ligne par station : flux, station_id, nom, lat, lon, capacite, velos_disponibles, places_disponibles, en_service, mis_a_jour
```

Un flux en panne apparaît dans `erreurs` sans bloquer les autres. Pour ajouter une ville : ajouter son `FLUX_<NOM>_URL` au `.env`.

## API SNCF

`lib/navitia.py` interroge l'API SNCF (Navitia, couverture `sncf`) pour chercher une gare et calculer des itinéraires en train, avec
les émissions de CO₂. Le token est `NAVITIA_TOKEN` dans le `.env`. Comme les flux, c'est le dashboard qui l'appelle : rien n'est stocké.
La couverture ne va qu'environ 30 jours en avant.

```python
from lib.navitia import id_gare, itineraires
itineraires(id_gare("87547000"), id_gare("87574004"), quand="2026-10-12 08:00")   # Paris Austerlitz → Blois-Chambord
```

`id_gare(code_uic)` convertit le `code_uic` d'une gare de la base en identifiant Navitia.

## Transformation

Nettoie les données de `data/` et les charge dans la base. Les flux temps réel (`FLUX_*`) n'y passent pas.

```bash
python src/transformation/transformation.py   # lance toutes les étapes dans l'ordre
```

Une étape par domaine, dans `src/transformation/` (nettoyage, transformation et chargement), chacune lançable seule :
- `gare.py` : gares_voyageurs + horaires_gares → `lieu`, `gare`, `gare_horaire`
- `culture.py` : basilic → `lieu` (culture), avec la gare la plus proche
- `tourisme.py` : datatourisme_place (attractions seulement) → `lieu` (tourisme), avec la gare la plus proche
- `sncf.py` (avec `gtfs.py`, commun à tous les réseaux) : horaires_sncf_gtfs → `reseau`, `ligne`, `circulation`, `calendrier`, `arret`, `passage`.
  Un arrêt dont le code UIC est celui d'une gare pointe vers elle ; les autres (cars TER, gares étrangères) reçoivent leur propre `lieu`
  (`arret_bus` ou `arret_train`), avec leur gare la plus proche si elle est à moins de 50 km.
- `transilien.py` : RER et Transilien d'Île-de-France Mobilités → mêmes tables. Les lignes TER de ce fichier sont écartées : le GTFS SNCF est
  la source des TER (40 % de ces circulations s'y trouvaient déjà). Arrêts rattachés à la gare de la base la plus proche à moins de 300 m
  dont le nom est compatible, ou à moins de 50 m.
- `trains_europeens.py` : Eurostar (rattaché par code UIC), Renfe AVE et Trenitalia France (rattachés par position) → mêmes tables.
- `bus.py` : 20 réseaux urbains (bus, tram, métro, bateau…) et Île-de-France Mobilités → mêmes tables. Chaque arrêt a son lieu `arret_bus` avec sa
  gare la plus proche (jamais rattaché à une gare). Pour l'Île-de-France, seules les lignes qui ne sont pas des trains sont gardées : les RER,
  Transilien et TER du même fichier sont déjà dans `transilien.py`. Environ 40 millions de passages : la base fait alors environ 9 Go et le
  chargement complet prend plusieurs dizaines de minutes.
- `evenement.py` : datatourisme_fma → `evenement`, `evenement_lieu`, `evenement_periode`, `lieu` (evenement)
- `velo.py` : stationnement cyclable (OpenStreetMap, gares du Centre-Val de Loire), Vélib', Vélo'v → `lieu` (station_velo), `station_velo`
  Les parkings OpenStreetMap à moins de 25 m d'un parking du fichier de la région sont écartés (mêmes parkings, la région prime) : voir l'en-tête de `velo.py`.

La Corse et l'outre-mer sont écartés pour l'instant. Pour ajouter un domaine : créer son module
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
