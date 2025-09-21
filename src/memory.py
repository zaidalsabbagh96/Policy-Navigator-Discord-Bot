from __future__ import annotations

import json
import time
import re
import os
import shutil
import tempfile
from pathlib import Path
from typing import List, Dict, Any, Optional
from threading import Lock

from src.utils import SESSIONS_DIR, log

# ---------------- I/O helpers (atomic write + lock) ---------------- #

_io_lock = Lock()

def _safe_write(path: Path, text: str) -> None:
    """
    Atomically write text to 'path' using a temp file + move.
    Works reliably on Windows (avoids WinError 32) and POSIX.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = None
    with _io_lock:
        try:
            tmp = tempfile.NamedTemporaryFile(
                delete=False, dir=path.parent, prefix=path.name + "._tmp_", mode="w", encoding="utf-8"
            )
            tmp.write(text)
            tmp.flush()
            tmp.close()
            # os.replace is atomic when possible on the platform
            os.replace(tmp.name, path)
        except Exception as e:
            log.warning(f"Atomic write failed for {path}: {e}")
            # Best-effort fallback
            try:
                if tmp and tmp.name and os.path.exists(tmp.name):
                    shutil.move(tmp.name, path)
            except Exception:
                pass
        finally:
            try:
                if tmp and tmp.name and os.path.exists(tmp.name):
                    os.unlink(tmp.name)
            except Exception:
                pass

# ---------------- In-memory cache ---------------- #

_CACHE: Dict[str, List[Dict[str, Any]]] = {}
_MAX_TURNS_DEFAULT = 10
_MAX_HISTORY_CHARS = 2000

def _path_for(session_id: str) -> Path:
    safe = re.sub(r"[^a-zA-Z0-9_\-:|]", "_", session_id)
    return Path(SESSIONS_DIR) / f"{safe}.json"

def load(session_id: str) -> List[Dict[str, Any]]:
    if session_id in _CACHE:
        return _CACHE[session_id]
    p = _path_for(session_id)
    if p.exists():
        # Be tolerant of a concurrent write by retrying a couple times.
        for _ in range(3):
            try:
                _CACHE[session_id] = json.loads(p.read_text(encoding="utf-8"))
                break
            except Exception as e:
                log.warning(f"Failed reading session {session_id} (retry): {e}")
                time.sleep(0.05)
        else:
            _CACHE[session_id] = []
    else:
        _CACHE[session_id] = []
    return _CACHE[session_id]

def save(session_id: str) -> None:
    p = _path_for(session_id)
    try:
        text = json.dumps(_CACHE.get(session_id, []), ensure_ascii=False, indent=2)
        _safe_write(p, text)
    except Exception as e:
        log.warning(f"Failed writing session {session_id}: {e}")

def clear(session_id: str) -> None:
    _CACHE[session_id] = []
    p = _path_for(session_id)
    try:
        if p.exists():
            # Use lock to avoid race with concurrent read/write
            with _io_lock:
                try:
                    p.unlink()
                except PermissionError:
                    # On Windows another process may still hold a handle briefly
                    try:
                        os.remove(p)
                    except Exception:
                        pass
    except Exception:
        pass

def add_turn(session_id: str, role: str, content: str, max_turns: int = _MAX_TURNS_DEFAULT) -> None:
    turns = load(session_id)
    turns.append({"t": time.time(), "role": role, "content": content})
    if len(turns) > max_turns * 2:
        turns[:] = turns[-(max_turns * 2):]
    _CACHE[session_id] = turns
    save(session_id)

def build_history_text(session_id: Optional[str], max_chars: int = _MAX_HISTORY_CHARS) -> str:
    if not session_id:
        return ""
    turns = load(session_id)
    if not turns:
        return ""
    chunks: List[str] = []
    for t in turns[-(_MAX_TURNS_DEFAULT * 2):]:
        role = "User" if t["role"] == "user" else "Assistant"
        chunks.append(f"{role}: {t['content']}")
    text = "\n".join(chunks)
    if len(text) > max_chars:
        text = text[-max_chars:]
    return text
