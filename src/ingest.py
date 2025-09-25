from __future__ import annotations

from pathlib import Path
import hashlib
import re
import time
import requests
from bs4 import BeautifulSoup

from src.utils import env, log, DATA_DIR, KAGGLE_DIR, WEB_DIR, UPLOADS_DIR


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
)
BLOCK_MARKERS = (
    "Request Access",
    "programmatic access to these sites is limited",
    "aggressive automated scraping",
)


def _is_blocked_html(text: str) -> bool:
    snippet = (text or "")[:20000].lower()
    return any(m.lower() in snippet for m in BLOCK_MARKERS)


def _find_govinfo_pdf_url(html_text: str) -> str | None:
    """
    FederalRegister pages typically include a link to the official PDF
    hosted on govinfo.gov. Try to extract it.
    """
    m = re.search(r'https?://www\.govinfo\.gov/content/pkg/[^"]+?\.pdf', html_text, re.I)
    if m:
        return m.group(0)
    m2 = re.search(r'https?://www\.govinfo\.gov/[^"]+?\.pdf', html_text, re.I)
    return m2.group(0) if m2 else None




def download_kaggle(dataset: str, target_dir: Path = KAGGLE_DIR) -> Path:
    """Download a Kaggle dataset like 'owner/dataset-name' into target_dir."""
    import kaggle

    target_dir.mkdir(parents=True, exist_ok=True)
    log.info(f"Downloading Kaggle dataset: {dataset}")
    kaggle.api.dataset_download_files(dataset, path=str(target_dir), unzip=True)
    return target_dir


def scrape_site(url: str, max_pages: int = 3, target_dir: Path = WEB_DIR) -> Path:
    """Very basic placeholder scraper. Keeps a real User-Agent and avoids re-adding the same host."""
    target_dir.mkdir(parents=True, exist_ok=True)
    seen = {url}
    queue = [url]
    count = 0

    headers = {"User-Agent": USER_AGENT}

    while queue and count < max_pages:
        u = queue.pop(0)
        try:
            resp = requests.get(u, timeout=20, headers=headers)
            html = resp.text
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

    kaggle_id = env("KAGGLE_DATASET_ID")
    seed_url = env("SEED_URL")

    if kaggle_id and not any(KAGGLE_DIR.iterdir()):
        download_kaggle(kaggle_id)

    if seed_url and not any(WEB_DIR.iterdir()):
        scrape_site(seed_url)

    return DATA_DIR


def _hash_name(name: str, extra: bytes | None = None) -> str:
    h = hashlib.sha256(name.encode("utf-8"))
    if extra:
        h.update(extra)
    return h.hexdigest()[:16]


def save_url_to_web(url: str) -> Path:
    """
    Fetch a public URL and save it under data/web/.
    Special case: when fetching a FederalRegister page that returns the
    'Request Access / programmatic access limited' blocker, follow the embedded
    govinfo.gov PDF link and save the PDF instead (so we can index real content).
    """
    WEB_DIR.mkdir(parents=True, exist_ok=True)
    headers = {"User-Agent": USER_AGENT}

    log.info(f"Fetching URL: {url}")
    resp = requests.get(url, timeout=30, headers=headers)
    resp.raise_for_status()
    html = resp.text

    if "federalregister.gov" in url.lower() and _is_blocked_html(html):
        log.info("Detected FederalRegister blocker page; trying govinfo PDF fallback…")
        pdf_url = _find_govinfo_pdf_url(html)
        if pdf_url:
            try:
                pdf_resp = requests.get(pdf_url, timeout=60, headers=headers)
                pdf_resp.raise_for_status()
                fname = f"federalregister_govinfo_{int(time.time())}.pdf"
                pdf_path = WEB_DIR / fname
                pdf_path.write_bytes(pdf_resp.content)
                log.info(f"Saved govinfo PDF to {pdf_path}")
                return pdf_path
            except Exception as e:
                log.warning(f"govinfo PDF fetch failed: {e}")

        fname = f"blocked_{int(time.time())}.html"
        out = WEB_DIR / fname
        out.write_text(html, encoding="utf-8", errors="ignore")
        log.info(f"Saved blocked HTML to {out}")
        return out

    slug = _hash_name(url)
    out = WEB_DIR / f"external-{slug}.html"
    out.write_text(html, encoding="utf-8", errors="ignore")
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
