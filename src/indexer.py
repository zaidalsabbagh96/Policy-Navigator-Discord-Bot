from pathlib import Path
from src.utils import env, log

def get_index():
    """Return an aiXplain Index instance by ID from .env (INDEX_ID)."""
    from aixplain.factories import IndexFactory
    index_id = env("INDEX_ID", required=True)
    log.info(f"Loading index: {index_id}")
    return IndexFactory.get(index_id)

def add_folder_to_index(index, folder: Path):
    """
    Walk a folder and add files to your index.
    Replace the body with the exact aiXplain SDK ingestion calls you use.
    """
    if not folder.exists():
        log.info(f"Folder not found, skipping: {folder}")
        return
    # TODO: implement according to your chosen ingestion method
    log.info(f"(stub) Would ingest files from: {folder}")
