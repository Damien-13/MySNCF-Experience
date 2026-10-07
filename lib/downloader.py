"""Téléchargement des datasets dans data/<source>/.

Les URLs sont dans .env : DATASET_<SOURCE>_URL=...
Usage : download(["basilic"])
"""
import os
import zipfile
from email.message import Message
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests
from dotenv import load_dotenv

load_dotenv()


def _filename(response):
    """Nom fourni par le serveur (Content-Disposition), sinon celui de l'URL."""
    header = Message()
    header["content-disposition"] = response.headers.get("content-disposition", "")
    name = header.get_filename()
    return Path(name).name if name else unquote(Path(urlparse(response.url).path).name)


def download(sources):
    """Télécharge chaque source demandée dans DATA_DIR/<source>/.

    Un .zip est décompressé dans le dossier de sa source.
    """
    data_dir = Path(os.environ.get("DATA_DIR", "data"))
    for source in sources:
        url = os.environ[f"DATASET_{source.upper()}_URL"]
        target = data_dir / source.lower()
        target.mkdir(parents=True, exist_ok=True)

        with requests.get(url, stream=True, timeout=60) as response:
            response.raise_for_status()
            file_path = target / _filename(response)
            with open(file_path, "wb") as out:
                for chunk in response.iter_content(1024 * 1024):
                    out.write(chunk)

        if zipfile.is_zipfile(file_path):
            with zipfile.ZipFile(file_path) as archive:
                archive.extractall(target)
            file_path.unlink()
