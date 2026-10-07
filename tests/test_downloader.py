import functools
import http.server
import threading
import zipfile

from lib.downloader import download


def test_download_csv_et_zip(tmp_path, monkeypatch):
    served = tmp_path / "served"
    served.mkdir()
    (served / "a.csv").write_text("x,y\n1,2\n")
    with zipfile.ZipFile(served / "multi.zip", "w") as z:
        z.writestr("one.csv", "1")
        z.writestr("two.csv", "2")

    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(served))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"

    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DATASET_PLAIN_URL", f"{base}/a.csv")
    monkeypatch.setenv("DATASET_MULTI_URL", f"{base}/multi.zip")
    try:
        download(["plain", "multi"])
    finally:
        server.shutdown()

    assert (tmp_path / "data" / "plain" / "a.csv").exists()
    assert sorted(p.name for p in (tmp_path / "data" / "multi").iterdir()) == ["one.csv", "two.csv"]
