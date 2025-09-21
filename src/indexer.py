# src/indexer.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Any

from src.utils import env, log, DATA_DIR

# aiXplain index access
def get_index():
    """Return an aiXplain Index instance by ID from .env (INDEX_ID)."""
    from aixplain.factories import IndexFactory
    index_id = env("INDEX_ID", required=True)
    log.info(f"Loading index: {index_id}")
    return IndexFactory.get(index_id)

# ------- smart-skip manifest (file mtime tracking) -------
_MANIFEST = Path(DATA_DIR) / ".index_manifest.json"

def _load_manifest() -> Dict[str, Any]:
    if _MANIFEST.exists():
        try:
            return json.loads(_MANIFEST.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}

def _save_manifest(m: Dict[str, Any]) -> None:
    try:
        _MANIFEST.write_text(json.dumps(m, indent=2), encoding="utf-8")
    except Exception as e:
        log.warning(f"Couldn't write manifest: {e}")

# ------- text extraction + index push -------
def _extract_text_from_path(path: Path) -> str | None:
    suff = path.suffix.lower()
    try:
        if suff in {".txt", ".md", ".html", ".htm", ".csv", ".json"}:
            return path.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        log.warning(f"Read failed for {path}: {e}")
    return None

def _push_text(index, text: str, metadata: Dict[str, Any]):
    """
    Try common ingestion methods across SDK variants.
    """
    methods = [
        ("add_document", dict(text=text, metadata=metadata)),
        ("addDocument", dict(text=text, metadata=metadata)),
        ("upsert", dict(text=text, metadata=metadata)),
        ("add", dict(text=text, metadata=metadata)),
        ("add_documents", [dict(text=text, metadata=metadata)]),
        ("addDocuments", [dict(text=text, metadata=metadata)]),
        ("upsert_many", [dict(text=text, metadata=metadata)]),
    ]
    for name, payload in methods:
        if hasattr(index, name):
            fn = getattr(index, name)
            try:
                return fn(payload) if isinstance(payload, list) else fn(**payload)
            except TypeError:
                try:
                    return fn(payload)
                except Exception:
                    pass
            except Exception:
                pass
    raise RuntimeError("Index object has no known ingestion method for plain text")

# ------- public API -------
def add_file_to_index(index, path: Path, source_hint: str = "") -> bool:
    """
    Index a single file if changed; record mtime in manifest for smart-skip.
    Returns True if indexed, False if skipped.
    """
    manifest = _load_manifest()
    key = str(path.resolve())
    try:
        mtime = path.stat().st_mtime
    except FileNotFoundError:
        return False

    prev = manifest.get(key)
    if prev and abs(prev.get("mtime", 0.0) - mtime) < 1e-9:
        return False  # unchanged

    text = _extract_text_from_path(path)
    if not text:
        log.info(f"Skip non-text or unreadable: {path}")
        manifest[key] = {"mtime": mtime, "skipped": True}
        _save_manifest(manifest)
        return False

    meta = {
        "path": key,
        "filename": path.name,
        "source": source_hint or "local",
    }
    _push_text(index, text, metadata=meta)
    manifest[key] = {"mtime": mtime, "size": path.stat().st_size, "skipped": False}
    _save_manifest(manifest)
    log.info(f"Indexed file: {path}")
    return True

def add_folder_to_index(index, folder: Path, source_hint: str = ""):
    """
    Walk a folder and add (changed) files to your index.
    """
    folder = Path(folder)
    if not folder.exists():
        log.info(f"Folder not found, skipping: {folder}")
        return
    count = 0
    for p in folder.rglob("*"):
        if p.is_file():
            try:
                if add_file_to_index(index, p, source_hint=source_hint):
                    count += 1
            except Exception as e:
                log.warning(f"Ingest error for {p}: {e}")
    if count:
        log.info(f"Ingested {count} file(s) from: {folder}")
