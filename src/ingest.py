from __future__ import annotations

from pathlib import Path
import hashlib
import requests
from bs4 import BeautifulSoup

from src.utils import env, log, DATA_DIR, KAGGLE_DIR, WEB_DIR, UPLOADS_DIR


def download_kaggle(dataset: str, target_dir: Path = KAGGLE_DIR) -> Path:
    """Download a Kaggle dataset like 'owner/dataset-name' into target_dir."""
    import kaggle

    target_dir.mkdir(parents=True, exist_ok=True)
    log.info(f"Downloading Kaggle dataset: {dataset}")
    kaggle.api.dataset_download_files(dataset, path=str(target_dir), unzip=True)
    return target_dir


def scrape_site(url: str, max_pages: int = 3, target_dir: Path = WEB_DIR) -> Path:
    """Very basic placeholder scraper. Replace with your marketplace tool if preferred."""
    target_dir.mkdir(parents=True, exist_ok=True)
    seen = {url}
    queue = [url]
    count = 0

    while queue and count < max_pages:
        u = queue.pop(0)
        try:
            html = requests.get(u, timeout=20).text
            (target_dir / f"page_{count}.html").write_text(html, encoding="utf-8")
            soup = BeautifulSoup(html, "lxml")
            base_domain = url.split("/")[2]
            for a in soup.select("a[href]"):
                href = a["href"]
                if href.startswith("http") and base_domain in href and href not in seen:
                    seen.add(href)
                    queue.append(href)
            count += 1
        except Exception as e:
            log.warning(f"Skip {u}: {e}")

    log.info(f"Scraped {count} page(s) from {url}")
    return target_dir


def ensure_data() -> Path:
    """Pull sources from Kaggle and a website using env vars if set."""
    DATA_DIR.mkdir(exist_ok=True)
    KAGGLE_DIR.mkdir(exist_ok=True)
    WEB_DIR.mkdir(exist_ok=True)
    UPLOADS_DIR.mkdir(exist_ok=True)

    kaggle_id = env("KAGGLE_DATASET_ID")  # e.g., "someuser/policy-dataset"
    seed_url = env(
        "SEED_URL"
    )  # e.g., "https://www.epa.gov/laws-regulations/regulations"

    if kaggle_id and not any(KAGGLE_DIR.iterdir()):
        download_kaggle(kaggle_id)

    # Only do an initial scrape if the folder is empty
    if seed_url and not any(WEB_DIR.iterdir()):
        scrape_site(seed_url)

    return DATA_DIR


# ---------- User-provided content helpers ----------


def _hash_name(name: str, extra: bytes | None = None) -> str:
    h = hashlib.sha256(name.encode("utf-8"))
    if extra:
        h.update(extra)
    return h.hexdigest()[:16]


def save_url_to_web(url: str) -> Path:
    """Fetch a public URL and save raw HTML to data/web/external-<hash>.html"""
    resp = requests.get(url, timeout=20)
    resp.raise_for_status()
    slug = _hash_name(url)
    out = WEB_DIR / f"external-{slug}.html"
    out.write_text(resp.text, encoding="utf-8")
    log.info(f"Saved URL to {out}")
    return out


def save_bytes_to_uploads(filename: str, data: bytes) -> Path:
    """Save uploaded bytes under data/uploads/<hash>-<filename>"""
    safe = filename.replace("\\", "/").split("/")[-1]
    stem = _hash_name(safe, extra=data)
    out = UPLOADS_DIR / f"{stem}-{safe}"
    out.write_bytes(data)
    log.info(f"Saved upload to {out}")
    return out
