from pathlib import Path
from src.utils import env, log

DATA_DIR = Path("data")

def download_kaggle(dataset: str, target_dir: Path = DATA_DIR / "kaggle") -> Path:
    """Download a Kaggle dataset like 'owner/dataset-name' into target_dir."""
    import kaggle
    target_dir.mkdir(parents=True, exist_ok=True)
    log.info(f"Downloading Kaggle dataset: {dataset}")
    kaggle.api.dataset_download_files(dataset, path=str(target_dir), unzip=True)
    return target_dir

def scrape_site(url: str, max_pages: int = 3, target_dir: Path = DATA_DIR / "web") -> Path:
    """Very basic placeholder scraper. Replace with your marketplace tool if preferred."""
    import requests
    from bs4 import BeautifulSoup

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
    kaggle_id = env("KAGGLE_DATASET_ID")  # e.g., "someuser/policy-dataset"
    seed_url  = env("SEED_URL")           # e.g., "https://www.epa.gov/laws-regulations/regulations"

    if kaggle_id and not (DATA_DIR / "kaggle").exists():
        download_kaggle(kaggle_id)

    if seed_url and not (DATA_DIR / "web").exists():
        scrape_site(seed_url)

    return DATA_DIR
