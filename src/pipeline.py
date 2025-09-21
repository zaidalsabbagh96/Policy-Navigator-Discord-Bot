from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional
from threading import Lock

from src.utils import log, env, env_bool
from src.ingest import ensure_data, save_url_to_web, save_bytes_to_uploads, scrape_site
from src.indexer import get_index, add_folder_to_index, add_file_to_index
from src.agents import build_agent
from src import memory

TOP_K = 5
_MAX_CONTEXT = 4000
_MIN_CTX_CHARS = 600

_agent_lock = Lock()
_agent_singleton = None
_agent_init_lock = Lock()
_index_singleton = None
_index_init_lock = Lock()


def _get_agent():
    global _agent_singleton
    if _agent_singleton is None:
        with _agent_init_lock:
            if _agent_singleton is None:
                _agent_singleton = build_agent()
    return _agent_singleton


def bootstrap():
    global _index_singleton
    if _index_singleton is None:
        with _index_init_lock:
            if _index_singleton is None:
                data_dir: Path = ensure_data()
                idx = get_index()
                add_folder_to_index(idx, data_dir / "kaggle", source_hint="kaggle")
                add_folder_to_index(idx, data_dir / "web", source_hint="web")
                add_folder_to_index(idx, data_dir / "uploads", source_hint="upload")
                _index_singleton = idx
    return _index_singleton


def ingest_url(url: str) -> str:
    index = bootstrap()
    path = save_url_to_web(url)
    did = add_file_to_index(index, path, source_hint="web:url")
    return f"Added URL ✔ ({'indexed' if did else 'skipped: unchanged'}) — {url}"


def ingest_file_bytes(filename: str, data: bytes) -> str:
    index = bootstrap()
    path = save_bytes_to_uploads(filename, data)
    did = add_file_to_index(index, path, source_hint="upload:file")
    return f"Added file ✔ ({'indexed' if did else 'skipped: unchanged'}) — {path.name}"


def _results_from_search(res: Any) -> List[Dict[str, Any]]:
    if res is None:
        return []
    if isinstance(res, list):
        return res
    if isinstance(res, dict):
        return res.get("details") or res.get("output") or res.get("results") or []
    data = getattr(res, "data", None)
    if isinstance(data, dict):
        return data.get("details") or data.get("output") or data.get("results") or []
    details = getattr(data, "details", None)
    if details is not None:
        return details
    output = getattr(data, "output", None)
    if isinstance(output, list):
        return output
    return []


def _build_context(results: List[Dict[str, Any]]) -> Tuple[str, List[str]]:
    chunks: List[str] = []
    sources: List[str] = []
    for item in results:
        if isinstance(item, str):
            txt, meta = item, {}
        else:
            txt = (
                item.get("data")
                or item.get("text")
                or item.get("content")
                or item.get("document")
                or ""
            )
            meta = item.get("metadata") or {}
        if txt:
            chunks.append(str(txt))
        src = (
            meta.get("url")
            or meta.get("path")
            or meta.get("source")
            or meta.get("filename")
        )
        if src:
            sources.append(str(src))
    context = "\n\n---\n\n".join(chunks).strip()
    if len(context) > _MAX_CONTEXT:
        context = context[:_MAX_CONTEXT]
    return context, sources


def _format_output(resp: Any) -> str:
    if hasattr(resp, "text") and resp.text:
        return str(resp.text).strip()

    data = getattr(resp, "data", None)
    out = None
    if isinstance(data, dict):
        out = (
            data.get("output")
            or data.get("text")
            or data.get("message")
            or data.get("content")
        )
    else:
        out = getattr(data, "output", None) or getattr(resp, "output", None)

    if isinstance(out, dict):
        summary = out.get("summary") or {}
        themes = summary.get("themes") or []
        if themes:
            lines = ["# GDPR enforcement themes"]
            for t in themes:
                theme = t.get("theme") or "Theme"
                desc = t.get("description") or ""
                cite = t.get("citation")
                line = f"- **{theme}** — {desc}"
                if cite:
                    line += f" _(cite: {cite})_"
                lines.append(line)
            return "\n".join(lines)
        return str(out).strip()

    if isinstance(out, str):
        return out.strip()

    if isinstance(data, dict):
        return str(data.get("output") or data).strip()
    return str(resp).strip()


def _split_sources(text: str) -> tuple[str, Optional[str]]:
    import re

    m = re.split(r"\n\*\*Sources\*\*\n", text, maxsplit=1)
    if len(m) == 2:
        return m[0].strip(), m[1].strip()
    return text.strip(), None


def _backfill_if_needed(
    index, query: str, history_text: str, retrieved_ctx: str
) -> Tuple[str, List[str]]:
    if len(retrieved_ctx) >= _MIN_CTX_CHARS:
        return retrieved_ctx, []
    boost = (history_text or "")[-600:]
    alt_query = f"{query}\n\nPrevious turns (for hints):\n{boost}" if boost else query
    try:
        res2 = index.search(alt_query, top_k=TOP_K)
        r2 = _results_from_search(res2)
        ctx2, src2 = _build_context(r2)
        if len(ctx2) > len(retrieved_ctx):
            retrieved_ctx, src_all = ctx2, src2
        else:
            src_all = []
    except Exception as e:
        log.warning(f"Backfill re-query failed: {e}")
        src_all = []

    if len(retrieved_ctx) < _MIN_CTX_CHARS and env_bool("USE_WEB_BACKFILL", False):
        seed = env("SEED_URL")
        if seed:
            try:
                log.info(f"Web backfill: scraping {seed} …")
                scrape_site(seed, max_pages=2)
                data_dir: Path = ensure_data()
                add_folder_to_index(index, data_dir / "web", source_hint="web")
                res3 = index.search(query, top_k=TOP_K)
                r3 = _results_from_search(res3)
                ctx3, src3 = _build_context(r3)
                if len(ctx3) > len(retrieved_ctx):
                    retrieved_ctx, src_all = ctx3, (src_all or []) + src3
            except Exception as e:
                log.warning(f"Web backfill failed: {e}")

    return retrieved_ctx, (src_all or [])


def _agent_run_with_retry(
    agent,
    query_for_agent: str,
    retrieved_ctx: str,
    retries: int = 5,
    base_delay: float = 0.2,
):
    last_err = None
    for attempt in range(retries):
        try:
            with _agent_lock:
                try:
                    return agent.run(query=query_for_agent, context=retrieved_ctx)
                except TypeError:
                    return agent.run(
                        {"query": query_for_agent, "context": retrieved_ctx}
                    )
        except Exception as e:
            msg = str(e)
            last_err = e
            if "functions.json" in msg or "WinError 32" in msg:
                time.sleep(base_delay * (attempt + 1))
                continue
            raise
    raise last_err


def answer(query: str, session_id: Optional[str] = None) -> str:
    index = bootstrap()
    agent = _get_agent()

    try:
        raw_res = index.search(query, top_k=TOP_K)
    except Exception as e:
        log.warning(f"Index retrieval failed: {e}")
        raw_res = None

    results = _results_from_search(raw_res)
    retrieved_ctx, sources = _build_context(results)
    history_text = memory.build_history_text(session_id) if session_id else ""

    retrieved_ctx, extra_sources = _backfill_if_needed(
        index, query, history_text, retrieved_ctx
    )
    if extra_sources:
        sources = (sources or []) + extra_sources

    header = (
        "You are answering a user question using the retrieved context below. "
        "If the context answers the question, answer directly and concisely with specifics. "
        "Avoid filler like 'I need to access/analyze the document.' "
        "If the context is insufficient, say briefly what is missing. "
        "Prefer citing concrete phrases when possible."
    )

    parts: List[str] = [header]
    if history_text:
        parts.append("Conversation history:\n" + history_text)
    if retrieved_ctx:
        parts.append("Retrieved context:\n" + retrieved_ctx)
    inline_ctx = "\n\n====\n\n".join(parts)[:_MAX_CONTEXT]

    query_for_agent = f"{query}\n\n---\n\n{inline_ctx}"

    try:
        resp = _agent_run_with_retry(agent, query_for_agent, retrieved_ctx)
    except Exception as e:
        ctx_preview = (inline_ctx[:800] + "…") if len(inline_ctx) > 800 else inline_ctx
        hints = (
            "\n".join(f"- {s}" for s in list(dict.fromkeys(sources))[:5]) or "(none)"
        )
        return (
            "[WIP] Agent call failed.\n\n"
            f"Query: {query}\n"
            f"Top sources:\n{hints}\n\n"
            f"Context preview:\n{ctx_preview}\n\n"
            f"Error: {e}"
        )

    out = _format_output(resp)

    if (not out or not out.strip()) and env_bool("ALLOW_GENERAL_ANSWER", True):
        try:
            with _agent_lock:
                try:
                    resp2 = agent.run(query=query)
                except TypeError:
                    resp2 = agent.run({"query": query})
            out2 = _format_output(resp2)
            if out2 and out2.strip():
                out = out2
        except Exception:
            pass

    if not out or not out.strip():
        out = (
            f"Sorry, I couldn’t extract a clear answer for: {query}\n\n"
            "Tip: try being more specific (mention a section, heading, or keyword)."
        )

    body_only, _ = _split_sources(out)
    if session_id:
        memory.add_turn(session_id, "user", query)
        memory.add_turn(session_id, "assistant", body_only)

    if sources:
        uniq = list(dict.fromkeys(sources))
        out += "\n\n**Sources**\n" + "\n".join(f"- {s}" for s in uniq)

    return out
