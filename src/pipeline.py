from pathlib import Path
from src.utils import log
from src.ingest import ensure_data
from src.indexer import get_index, add_folder_to_index
from src.agents import build_agent


def bootstrap():
    """Make sure local sources exist and are ingested into your index."""
    data_dir = ensure_data()
    index = get_index()
    add_folder_to_index(index, data_dir / "kaggle")
    add_folder_to_index(index, data_dir / "web")
    return index


def answer(query: str) -> str:
    """
    End-to-end: ensure data/index, retrieve top chunks, build context, then call the agent.
    Works for both single agents (.text) and team agents (.data["output"]).
    """
    index = bootstrap()
    agent = build_agent()

    try:
        results = index.search(query, top_k=5)
    except Exception as e:
        log.warning(f"Index retrieval failed or not wired yet: {e}")
        results = []

    context_parts, sources = [], []
    for r in results or []:
        if isinstance(r, str):
            txt = r
            meta = {}
        else:
            txt = (r.get("text") or r.get("content") or "").strip()
            meta = r.get("metadata") or {}
        if txt:
            context_parts.append(txt)
        src = meta.get("url") or meta.get("path") or meta.get("source")
        if src:
            sources.append(str(src))
    context = "\n\n---\n\n".join(context_parts).strip()

    try:
        resp = agent.run(query=query, context=context)

        if hasattr(resp, "text") and resp.text:
            out = resp.text
        elif hasattr(resp, "data") and isinstance(resp.data, dict):
            out = resp.data.get("output") or resp.data.get("text") or str(resp.data)
        else:
            out = str(resp)

        if sources:
            uniq = []
            for s in sources:
                if s not in uniq:
                    uniq.append(s)
            out += "\n\nSources:\n" + "\n".join(f"- {s}" for s in uniq)
        return out

    except TypeError as e:
        log.warning(f"agent.run kwargs rejected ({e}); retrying with dict input.")
        try:
            resp = agent.run({"query": query, "context": context})
            if hasattr(resp, "text") and resp.text:
                return resp.text
            if hasattr(resp, "data") and isinstance(resp.data, dict):
                return resp.data.get("output") or str(resp.data)
            return str(resp)
        except Exception as e2:
            pass

    except Exception as e:
        log.warning(f"Agent call failed: {e}")

    ctx_preview = (context[:800] + "…") if len(context) > 800 else context
    hints = "\n".join(f"- {s}" for s in list(dict.fromkeys(sources))[:5]) or "(none)"
    return (
        "[WIP] Agent call not wired or failed.\n\n"
        f"Query: {query}\n"
        f"Top sources:\n{hints}\n\n"
        f"Context preview:\n{ctx_preview}"
    )
