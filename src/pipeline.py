# src/pipeline.py
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

from src.utils import log
from src.ingest import ensure_data
from src.indexer import get_index, add_folder_to_index
from src.agents import build_agent

TOP_K = 5


def bootstrap():
    """
    Make sure local sources exist and are ingested into your index.
    Safe to call every run (idempotent).
    """
    data_dir: Path = ensure_data()
    index = get_index()
    add_folder_to_index(index, data_dir / "kaggle")
    add_folder_to_index(index, data_dir / "web")
    return index


def _results_from_search(res: Any) -> List[Dict[str, Any]]:
    """
    Normalize the result of index.search(...) into a list of dicts.
    Handles aiXplain ModelResponse objects and plain lists/dicts.
    """
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
    """
    Build a context string for the agent from search results, and collect sources.
    Prefers 'data' for text, with fallbacks to 'text'/'content'/'document'.
    """
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
        src = meta.get("url") or meta.get("path") or meta.get("source")
        if src:
            sources.append(str(src))

    context = "\n\n---\n\n".join(chunks).strip()
    return context, sources


def _format_output(resp: Any) -> str:
    """
    Normalize aiXplain single/team responses into readable text.

    - Single agents often expose .text
    - Team/structured flows often return .data.output (sometimes a rich dict)
    """
    if hasattr(resp, "text") and resp.text:
        return str(resp.text).strip()

    data = getattr(resp, "data", None)
    out = None
    if isinstance(data, dict):
        out = data.get("output") or data.get("text") or data.get("message") or data.get("content")
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

    # Fallbacks
    if isinstance(data, dict):
        return str(data.get("output") or data).strip()
    return str(resp).strip()


def answer(query: str) -> str:
    """
    End-to-end: ensure data/index, retrieve top chunks, build context, then call the agent.
    Works for both single agents (.text) and team agents (.data['output']).
    """
    index = bootstrap()
    agent = build_agent()

    try:
        raw_res = index.search(query, top_k=TOP_K)
    except Exception as e:
        log.warning(f"Index retrieval failed: {e}")
        raw_res = None

    results = _results_from_search(raw_res)

    context, sources = _build_context(results)

    try:
        resp = agent.run(query=query, context=context)
    except TypeError:
        resp = agent.run({"query": query, "context": context})
    except Exception as e:
        ctx_preview = (context[:800] + "…") if len(context) > 800 else context
        hints = "\n".join(f"- {s}" for s in list(dict.fromkeys(sources))[:5]) or "(none)"
        return (
            "[WIP] Agent call failed.\n\n"
            f"Query: {query}\n"
            f"Top sources:\n{hints}\n\n"
            f"Context preview:\n{ctx_preview}\n\n"
            f"Error: {e}"
        )

    out = _format_output(resp)

    if sources:
        uniq = list(dict.fromkeys(sources))
        out += "\n\n**Sources**\n" + "\n".join(f"- {s}" for s in uniq)

    return out
