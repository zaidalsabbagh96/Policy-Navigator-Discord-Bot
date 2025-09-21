from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Any, Iterable, Tuple, List
from tempfile import TemporaryDirectory

from src.utils import env, log

DATA_DIR = env("DATA_DIR") or str(Path.cwd() / "data")

# Chunking to avoid 500s from huge payloads
_CHUNK_CHARS = 1800
_CHUNK_OVERLAP = 200
_BATCH_SIZE = 50


def get_index():
    from aixplain.factories import IndexFactory

    index_id = env("INDEX_ID", required=True)
    log.info(f"Loading index: {index_id}")
    return IndexFactory.get(index_id)


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


def _html_to_text(html: str) -> str:
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "lxml")
        # remove script/style
        for bad in soup(["script", "style", "noscript"]):
            bad.decompose()
        return soup.get_text(" ", strip=True)
    except Exception:
        return html


def _extract_text_from_path(path: Path) -> str | None:
    suff = path.suffix.lower()
    try:
        if suff in {".txt", ".md", ".csv", ".json"}:
            return path.read_text(encoding="utf-8", errors="ignore")
        if suff in {".html", ".htm"}:
            raw = path.read_text(encoding="utf-8", errors="ignore")
            return _html_to_text(raw)
        if suff == ".pdf":
            try:
                from PyPDF2 import PdfReader

                reader = PdfReader(str(path))
                return "\n".join((page.extract_text() or "") for page in reader.pages)
            except Exception as e:
                log.info(f"PDF text extraction skipped for {path}: {e}")
                return None
    except Exception as e:
        log.warning(f"Read failed for {path}: {e}")
    return None


def _chunk_text(
    text: str, max_chars: int = _CHUNK_CHARS, overlap: int = _CHUNK_OVERLAP
) -> List[str]:
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]
    chunks: List[str] = []
    start = 0
    while start < len(text):
        end = start + max_chars
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start = end - overlap
        if start < 0:
            start = 0
    return chunks


# ---------- SDK helpers ----------


def _ok(ret: Any) -> bool:
    if ret is None:
        return True
    status = None
    try:
        status = getattr(ret, "status", None)
        if not status:
            data = getattr(ret, "data", None)
            if isinstance(data, dict):
                status = data.get("status") or data.get("state")
    except Exception:
        pass
    if isinstance(status, str) and status.upper() in {"FAILED", "ERROR"}:
        return False
    if isinstance(ret, dict):
        s = (ret.get("status") or ret.get("state") or "").upper()
        if s in {"FAILED", "ERROR"}:
            return False
    return True


def _call(index, name: str, payload) -> Tuple[bool, Any]:
    if not hasattr(index, name):
        return False, None
    fn = getattr(index, name)
    try:
        ret = fn(**payload) if isinstance(payload, dict) else fn(payload)
    except TypeError:
        try:
            ret = fn(payload)
        except Exception:
            return False, None
    except Exception:
        return False, None
    return (_ok(ret), ret)


def _try_many(index, name: str, payloads: Iterable[Any]) -> Tuple[bool, Any]:
    for p in payloads:
        ok, ret = _call(index, name, p)
        if ok:
            return True, ret
    return False, None


# ---------- Ingest using Record(value, attributes) ----------


def _record_upsert(index, texts: List[str], metadatas: List[Dict[str, Any]]) -> bool:
    try:
        from aixplain.modules.model.record import Record
    except Exception:
        return False

    recs = [Record(value=t, attributes=(m or {})) for t, m in zip(texts, metadatas)]
    # batch to avoid supplier size limits
    for i in range(0, len(recs), _BATCH_SIZE):
        batch = recs[i : i + _BATCH_SIZE]
        ok, _ = _try_many(index, "upsert", [dict(records=batch), batch])
        if not ok:
            return False
    return True


def _push_text(index, text: str, metadata: Dict[str, Any]):
    chunks = _chunk_text(text)
    if not chunks:
        return
    metas = [
        {**metadata, "chunk": i, "total_chunks": len(chunks)}
        for i, _ in enumerate(chunks)
    ]
    if _record_upsert(index, chunks, metas):
        return

    # Fallback shapes (older SDKs)
    for i in range(0, len(chunks), _BATCH_SIZE):
        c = chunks[i : i + _BATCH_SIZE]
        m = metas[i : i + _BATCH_SIZE]
        legacy = [
            ("ingest", dict(texts=c, metadatas=m)),
            (
                "ingest",
                dict(documents=[{"text": t, "metadata": mm} for t, mm in zip(c, m)]),
            ),
            ("add_documents", [{"text": t, "metadata": mm} for t, mm in zip(c, m)]),
            (
                "upsert",
                dict(records=[{"text": t, "metadata": mm} for t, mm in zip(c, m)]),
            ),
            ("upsert", [{"text": t, "metadata": mm} for t, mm in zip(c, m)]),
        ]
        for name, payload in legacy:
            ok, _ = _try_many(index, name, [payload])
            if ok:
                break
        else:
            # try single-record fallbacks before giving up
            for t, mm in zip(c, m):
                single_tries = [
                    ("upsert", dict(records=[{"text": t, "metadata": mm}])),
                    ("add_document", dict(text=t, metadata=mm)),
                ]
                ok, _ = _try_many(index, name="upsert", payloads=[single_tries[0][1]])
                if not ok:
                    _try_many(
                        index, name=single_tries[1][0], payloads=[single_tries[1][1]]
                    )


def _push_file(index, path: Path, metadata: Dict[str, Any], _is_temp: bool = False):
    text = _extract_text_from_path(path)
    if text:
        _push_text(index, text, metadata)
        return

    placeholder = f"[file: {path.name}]"
    _push_text(
        index, placeholder, {**metadata, "filename": path.name, "path": str(path)}
    )


# ---------- public API ----------


def add_file_to_index(index, path: Path, source_hint: str = "") -> bool:
    manifest = _load_manifest()
    key = str(path.resolve())
    try:
        mtime = path.stat().st_mtime
    except FileNotFoundError:
        return False

    prev = manifest.get(key)
    if prev and abs(prev.get("mtime", 0.0) - mtime) < 1e-9:
        return False

    meta = {"path": key, "filename": path.name, "source": source_hint or "local"}

    did = False
    try:
        _push_file(index, path, meta)
        did = True
    except Exception as e:
        log.warning(f"Ingest error for {path}: {e}")
        did = False

    manifest[key] = {
        "mtime": mtime,
        "size": path.stat().st_size if path.exists() else 0,
        "skipped": not did,
    }
    _save_manifest(manifest)

    if did:
        log.info(f"Indexed file: {path}")
    else:
        log.info(f"Skipped (ingest failed): {path}")
    return did


def add_folder_to_index(index, folder: Path, source_hint: str = ""):
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
