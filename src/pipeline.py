from __future__ import annotations
import re
from bs4 import BeautifulSoup
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
_MAX_CONTEXT = 2500
_MIN_CTX_CHARS = 600
_EXTRA_INGESTED_MAX_CHARS = 1400

_agent_lock = Lock()
_agent_singleton = None
_agent_init_lock = Lock()
_index_singleton = None
_index_init_lock = Lock()

_recent_ingested_cache = {}


def _get_agent():
    global _agent_singleton
    if _agent_singleton is None:
        with _agent_init_lock:
            if _agent_singleton is None:
                _agent_singleton = build_agent()
                log.info(f"Agent created: {type(_agent_singleton)}")
    return _agent_singleton


def bootstrap():
    global _index_singleton
    if _index_singleton is None:
        with _index_init_lock:
            if _index_singleton is None:
                data_dir: Path = ensure_data()
                idx = get_index()
                log.info(f"Index loaded: {type(idx)}")
                add_folder_to_index(idx, data_dir / "kaggle", source_hint="kaggle")
                add_folder_to_index(idx, data_dir / "web", source_hint="web")
                add_folder_to_index(idx, data_dir / "uploads", source_hint="upload")
                _index_singleton = idx
    return _index_singleton


def ingest_url(url: str, session_id: Optional[str] = None) -> str:
    index = bootstrap()
    primary_path = save_url_to_web(url)
    did_any = False
    ingested_paths = []
    
    if primary_path and primary_path.exists():
        did_any = add_file_to_index(index, primary_path, source_hint="web:url") or did_any
        ingested_paths.append(primary_path)
    
    scraped = scrape_site(url, max_pages=1)
    scraped_paths = scraped if isinstance(scraped, list) else ([scraped] if scraped else [])
    for p in scraped_paths:
        if p and isinstance(p, Path) and p.exists():
            did_any = add_file_to_index(index, p, source_hint="web:scrape") or did_any
            ingested_paths.append(p)
    
    try:
        from src.ingest import extract_and_save_linked_pdfs
        extra_pdf_paths = extract_and_save_linked_pdfs(primary_path)
        for pdf in extra_pdf_paths:
            if pdf.exists():
                did_any = add_file_to_index(index, pdf, source_hint="web:pdf") or did_any
                ingested_paths.append(pdf)
    except Exception as e:
        log.warning(f"PDF link extract failed: {e}")
    
    if session_id:
        try:
            memory.add_turn(session_id, "system", f"INGESTED_URL {url}")
            for path in ingested_paths:
                memory.add_turn(session_id, "system", f"INGESTED_PATH {path.as_posix()}")
            
            if session_id not in _recent_ingested_cache:
                _recent_ingested_cache[session_id] = []
            _recent_ingested_cache[session_id].extend(ingested_paths)
            
        except Exception as e:
            log.warning(f"Could not record ingest in memory: {e}")
    
    status = "indexed" if did_any else "skipped: blocked or unchanged"
    return f"Added URL ✓ ({status}) — {url}"


def ingest_file_bytes(filename: str, data: bytes, session_id: Optional[str] = None) -> str:
    index = bootstrap()
    path = save_bytes_to_uploads(filename, data)
    did = add_file_to_index(index, path, source_hint="upload:file")
    
    if session_id:
        try:
            memory.add_turn(session_id, "system", f"INGESTED_FILE {filename}")
            memory.add_turn(session_id, "system", f"INGESTED_PATH {path.as_posix()}")
            
            if session_id not in _recent_ingested_cache:
                _recent_ingested_cache[session_id] = []
            _recent_ingested_cache[session_id].append(path)
            
        except Exception as e:
            log.warning(f"Could not record file-ingest in memory: {e}")
    
    return f"Added file ✓ ({'indexed' if did else 'skipped: unchanged'}) — {path.name}"


def _results_from_search(res: Any) -> List[Dict[str, Any]]:
    log.info(f"Search result type: {type(res)}")
    if hasattr(res, "__dict__"):
        log.info(f"Search result attributes: {list(vars(res).keys())}")
    if res is None:
        return []
    if hasattr(res, "details") and res.details:
        log.info(f"Found details with {len(res.details)} items")
        return res.details
    if isinstance(res, list):
        return res
    if isinstance(res, dict):
        for key in ["details", "output", "results", "data"]:
            if key in res and isinstance(res[key], list):
                return res[key]
        if "data" in res and res["data"]:
            return [{"data": res["data"], "metadata": {}}]
    data = getattr(res, "data", None)
    if data is not None:
        if isinstance(data, dict):
            for key in ["details", "output", "results"]:
                if key in data and isinstance(data[key], list):
                    return data[key]
            return [{"data": str(data), "metadata": {}}]
        if isinstance(data, list):
            return data
        if data:
            return [{"data": str(data), "metadata": {}}]
    details = getattr(res, "details", None)
    if details is not None:
        if isinstance(details, list):
            return details
        return [{"data": str(details), "metadata": {}}]
    return [{"data": str(res), "metadata": {}}]


def _build_context(results: List[Dict[str, Any]]) -> Tuple[str, List[str]]:
    log.info(f"Building context from {len(results)} results")
    chunks: List[str] = []
    sources: List[str] = []
    for i, item in enumerate(results):
        log.info(f"Result {i}: {type(item)}")
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
            log.info(
                f"Result {i} keys: {list(item.keys()) if isinstance(item, dict) else 'N/A'}"
            )
            log.info(f"Result {i} text length: {len(str(txt))}")
        if txt and str(txt).strip():
            chunks.append(str(txt).strip())
        src = None
        if meta:
            src = (
                meta.get("url")
                or meta.get("path")
                or meta.get("source")
                or meta.get("filename")
                or meta.get("dataset")
            )
        if not src and isinstance(item, dict):
            src = item.get("document") or item.get("source") or item.get("url")
        
        if src:
            if isinstance(src, str):
                if src.startswith('http'):
                    sources.append(src)
                elif 'federalregister.gov' in src or 'whitehouse.gov' in src or 'epa.gov' in src:
                    sources.append(src)
                elif not ('data/uploads/' in src or 'data/web/' in src or 'C:\\' in src or '/Users/' in src):
                    sources.append(src)
                    
    context = "\n\n---\n\n".join(chunks).strip()
    if len(context) > _MAX_CONTEXT:
        context = context[:_MAX_CONTEXT]
    log.info(f"Final context length: {len(context)}")
    log.info(f"Sources found: {len(sources)}")
    log.info(
        f"Context preview: {context[:200]}..." if context else "No context generated"
    )
    return context, sources


def _convert_json_to_natural(data: dict) -> str:
    if not isinstance(data, dict):
        return str(data)
    if "definition" in data:
        result = data["definition"]
        if "purpose" in data:
            result += f" {data['purpose']}"
        if "key_principles" in data and isinstance(data["key_principles"], list):
            result += (
                f"\n\nKey principles include: {', '.join(data['key_principles'])}."
            )
        return result
    if "compliance_requirements" in data and isinstance(
        data["compliance_requirements"], list
    ):
        result = "Main compliance requirements include:\n\n"
        for req in data["compliance_requirements"][:5]:
            if isinstance(req, dict):
                name = req.get("name", "Requirement")
                desc = req.get("description", "")
                result += f"• **{name}**: {desc}\n"
        return result.strip()
    if "summary" in data and isinstance(data["summary"], dict):
        summary = data["summary"]
        result = ""
        if "global_trends" in summary:
            result += f"{summary['global_trends']}\n\n"
        if "key_regulations" in summary and isinstance(
            summary["key_regulations"], list
        ):
            result += "Key regulations include:\n"
            for reg in summary["key_regulations"][:3]:
                if isinstance(reg, dict):
                    name = reg.get("name", "Regulation")
                    desc = reg.get("description", "")
                    result += f"• **{name}**: {desc}\n"
        return result.strip()
    if len(data) == 1:
        key, value = next(iter(data.items()))
        if isinstance(value, str):
            return f"{key.replace('_', ' ').title()}: {value}"
        elif isinstance(value, list):
            items = [str(item) for item in value[:3]]
            return f"{key.replace('_', ' ').title()}: {', '.join(items)}"
    parts = []
    for key, value in data.items():
        if isinstance(value, str) and len(value) < 200:
            parts.append(f"{key.replace('_', ' ').title()}: {value}")
        elif isinstance(value, list) and len(value) <= 5:
            items = [str(item) for item in value]
            parts.append(f"{key.replace('_', ' ').title()}: {', '.join(items)}")
    return ". ".join(parts[:3]) + "." if parts else str(data)


def _debug_agent_response(resp: Any) -> None:
    log.info(f"=== AGENT RESPONSE DEBUG ===")
    log.info(f"Response type: {type(resp)}")
    log.info(
        f"Response attributes: {list(vars(resp).keys()) if hasattr(resp, '__dict__') else 'No __dict__'}"
    )
    if hasattr(resp, "data") and resp.data:
        data = resp.data
        log.info(f"Response.data type: {type(data)}")
        if hasattr(data, "to_dict"):
            try:
                data_dict = data.to_dict()
                log.info(f"Data as dict: {data_dict}")
            except Exception as e:
                log.info(f"Could not convert to dict: {e}")
        if hasattr(data, "__dict__"):
            for attr, value in vars(data).items():
                log.info(f"data.{attr} = {repr(value)[:200]}...")
    log.info(f"Raw response string: {str(resp)[:500]}...")
    log.info(f"=== END DEBUG ===")


def _format_output(resp: Any) -> str:
    log.info(f"Formatting output from: {type(resp)}")
    if hasattr(resp, "__dict__"):
        log.info(f"Response attributes: {list(vars(resp).keys())}")
    for attr in ("text", "output", "message", "content"):
        v = getattr(resp, attr, None)
        if isinstance(v, str) and v.strip():
            log.info(f"Found text in {attr}: {v[:100]}...")
            return v.strip()
    data = getattr(resp, "data", None)
    if data is not None:
        log.info(f"Response.data type: {type(data)}")
        try:
            if hasattr(data, "to_dict"):
                data = data.to_dict()
        except Exception:
            pass
        if isinstance(data, dict):
            log.info(f"Data keys: {list(data.keys())}")
            for k in ("output", "text", "message", "content"):
                v = data.get(k)
                if v is not None:
                    log.info(f"Found data.{k}: type={type(v)}, value={str(v)[:100]}...")
                    if isinstance(v, str) and v.strip():
                        try:
                            import json
                            parsed = json.loads(v)
                            if isinstance(parsed, dict):
                                return _convert_json_to_natural(parsed)
                        except:
                            pass
                        return v.strip()
                    elif isinstance(v, dict):
                        return _convert_json_to_natural(v)
                    elif v:
                        return str(v).strip()
            if "intermediate_steps" in data and data["intermediate_steps"]:
                steps = data["intermediate_steps"]
                log.info(
                    f"Checking intermediate_steps: {len(steps) if isinstance(steps, list) else type(steps)}"
                )
                if isinstance(steps, list) and steps:
                    for step in reversed(steps):
                        if isinstance(step, dict) and "output" in step:
                            output = step["output"]
                            log.info(f"Found step output: {str(output)[:100]}...")
                            if isinstance(output, str) and output.strip():
                                return output.strip()
            summary = " ".join(
                f"{k}: {v}" for k, v in data.items() if v and str(v).strip()
            )
            if summary:
                return summary
    result = str(resp).strip()
    log.info(f"Fallback string representation: {result[:200]}...")
    return result


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
    log.info(f"Context too short ({len(retrieved_ctx)} chars), attempting backfill")
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
    session_id: Optional[str] = None,
    retries: int = 3,
    base_delay: float = 0.25,
):
    log.info(f"Calling agent with query length: {len(query_for_agent)}")
    log.info(f"Agent type: {type(agent)}")
    last_err = None
    for attempt in range(retries):
        try:
            args = {"query": query_for_agent}
            if retrieved_ctx:
                args["context"] = retrieved_ctx
            if session_id:
                args["session_id"] = session_id
            log.info(
                f"Attempt {attempt + 1}: Calling agent with args keys: {list(args.keys())}"
            )
            with _agent_lock:
                result = agent.run(args)
            log.info(f"Agent call successful on attempt {attempt + 1}")
            if hasattr(result, "data"):
                data = result.data
                if hasattr(data, "output") and data.output:
                    log.info(f"Got valid output: {str(data.output)[:100]}...")
                    return result
                else:
                    log.warning(f"Response has no output, retrying...")
                    with _agent_lock:
                        str_result = agent.run(query_for_agent)
                    if (
                        hasattr(str_result, "data")
                        and hasattr(str_result.data, "output")
                        and str_result.data.output
                    ):
                        log.info("Plain string query successful")
                        return str_result
                    with _agent_lock:
                        dict_result = agent.run({"query": query_for_agent})
                    if (
                        hasattr(dict_result, "data")
                        and hasattr(dict_result.data, "output")
                        and dict_result.data.output
                    ):
                        log.info("Dict with only 'query' successful")
                        return dict_result
                    simple_query = query_for_agent.split("\n---\n")[0]
                    args2 = {"query": simple_query, "context": retrieved_ctx}
                    if session_id:
                        args2["session_id"] = session_id
                    log.info("Trying alternative format with separate context (legacy)")
                    with _agent_lock:
                        result = agent.run(args2)
                    if (
                        hasattr(result, "data")
                        and hasattr(result.data, "output")
                        and result.data.output
                    ):
                        log.info("Alternative format successful")
                        return result
            return result
        except Exception as e:
            last_err = e
            log.error(f"Agent call attempt {attempt + 1} failed: {e}")
            if "query" in str(e) or "TypeError" in str(e):
                try:
                    log.info("Trying simplified query without embedded context")
                    simple_query = query_for_agent.split("\n")[0]
                    with _agent_lock:
                        result = agent.run(simple_query)
                    if (
                        hasattr(result, "data")
                        and hasattr(result.data, "output")
                        and result.data.output
                    ):
                        log.info("Simplified query successful")
                        return result
                except Exception as e2:
                    log.error(f"Simplified query also failed: {e2}")
            time.sleep(base_delay * (attempt + 1))
    if last_err:
        log.error(f"All agent call attempts failed. Last error: {last_err}")
        raise last_err
    raise RuntimeError("agent.run failed with all attempts")


def _read_text_from_file(p: Path) -> str:
    try:
        text = p.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        try:
            text = p.read_bytes().decode("latin-1", errors="ignore")
        except Exception:
            return ""
    low = text.lower()
    if (
        ("request access" in low and "federalregister.gov" in low)
        or "programmatic access to these sites is limited" in low
        or "enable javascript and cookies" in low
        or "access denied" in low
        or "verify you are a human" in low
    ):
        log.info(f"Skipping blocked/placeholder page: {p}")
        return ""
    if "<html" in low:
        try:
            soup = BeautifulSoup(text, "html.parser")
            for bad in soup(["script", "style", "noscript"]):
                bad.decompose()
            text = soup.get_text(" ", strip=True)
        except Exception:
            pass
    return text[:_MAX_CONTEXT]


def _latest_file_in(dirpath: Path, patterns: tuple[str, ...]) -> Optional[Path]:
    try:
        candidates: list[Path] = []
        for pat in patterns:
            candidates.extend(dirpath.rglob(pat))
        if not candidates:
            return None
        candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return candidates[0]
    except Exception:
        return None


def _maybe_attach_recent_ingested_context(
    session_id: Optional[str],
) -> tuple[str, list[str]]:
    sources: list[str] = []
    chosen_path: Optional[Path] = None
    chosen_url: Optional[str] = None
    history = ""
    
    if session_id and session_id in _recent_ingested_cache:
        recent_paths = _recent_ingested_cache[session_id]
        if recent_paths:
            chosen_path = recent_paths[-1]
            log.info(f"Using cached recent path: {chosen_path}")
    
    if chosen_path is None:
        try:
            if session_id:
                history = memory.build_history_text(session_id) or ""
        except Exception:
            history = ""
        
        if history:
            m_paths = re.findall(r"INGESTED_PATH\s+(.+)", history)
            if m_paths:
                last_path = m_paths[-1].strip()
                p = Path(last_path)
                if p.exists() and p.is_file():
                    chosen_path = p
            m_urls = re.findall(r"INGESTED_URL\s+(\S+)", history)
            if m_urls:
                chosen_url = m_urls[-1].strip()
    
    if chosen_path is None:
        try:
            data_root: Path = ensure_data()
            web_dir = data_root / "web"
            up_dir = data_root / "uploads"
            web_latest = _latest_file_in(web_dir, ("*.html", "*.htm", "*.txt", "*.md"))
            up_latest = _latest_file_in(
                up_dir, ("*.txt", "*.md", "*.html", "*.htm", "*.*")
            )

            def mtime_or_0(p: Optional[Path]) -> float:
                try:
                    return p.stat().st_mtime if p else 0.0
                except Exception:
                    return 0.0

            chosen_path = (
                web_latest
                if mtime_or_0(web_latest) >= mtime_or_0(up_latest)
                else up_latest
            )
        except Exception:
            chosen_path = None
    
    if chosen_path and chosen_path.exists():
        text = _read_text_from_file(chosen_path)
        low = text.lower()
        if (
            not text.strip()
            or ("request access" in low and "federalregister.gov" in low)
            or "programmatic access to these sites is limited" in low
            or "enable javascript and cookies" in low
            or "access denied" in low
            or "verify you are a human" in low
        ):
            log.info(f"Skip attaching blocked/placeholder content: {chosen_path}")
            return "", []
        if chosen_url:
            sources.append(chosen_url)
        sources.append(chosen_path.name)
        if len(text) > _EXTRA_INGESTED_MAX_CHARS:
            text = text[:_EXTRA_INGESTED_MAX_CHARS]
        return text, sources
    return "", []


def answer(query: str, session_id: Optional[str] = None) -> str:
    log.info(f"Processing query: {query[:100]}...")
    index = bootstrap()
    agent = _get_agent()
    
    trigger_phrases = (
        "the document i just ingested",
        "the document i ingested",
        "this document",
        "from the document i just added",
        "from the url i just added",
        "from the file i just uploaded",
        "the document we just added",
        "i just ingested",
        "document i just"
    )
    wants_ingested_doc = any(p in query.lower() for p in trigger_phrases)
    
    extra_text, extra_sources = _maybe_attach_recent_ingested_context(session_id)
    
    retrieved_ctx = ""
    sources = []
    
    if wants_ingested_doc and extra_text:
        log.info("User asking about recently ingested document - prioritizing that content")
        retrieved_ctx = extra_text
        sources = extra_sources
        
        try:
            log.info("Also searching index for additional context...")
            raw_res = index.search(query, top_k=3)
            results = _results_from_search(raw_res)
            index_ctx, index_sources = _build_context(results)
            if index_ctx:
                retrieved_ctx = retrieved_ctx + "\n\n---\n\n" + index_ctx[:500]
                sources.extend(index_sources)
        except Exception as e:
            log.warning(f"Index search failed: {e}")
    else:
        try:
            log.info("Searching index...")
            raw_res = index.search(query, top_k=TOP_K)
            log.info("Index search completed")
            results = _results_from_search(raw_res)
            retrieved_ctx, sources = _build_context(results)
            
            if extra_text:
                log.info("Adding recent ingested content to context")
                retrieved_ctx = extra_text + "\n\n---\n\n" + retrieved_ctx
                sources = extra_sources + sources
        except Exception as e:
            log.warning(f"Index retrieval failed: {e}")
            if extra_text:
                retrieved_ctx = extra_text
                sources = extra_sources
    
    history_text = memory.build_history_text(session_id) if session_id else ""
    
    retrieved_ctx, backfill_sources = _backfill_if_needed(
        index, query, history_text, retrieved_ctx
    )
    if backfill_sources:
        sources = backfill_sources
    
    header = (
        "You are answering a user question using the retrieved context below. "
        "The context includes documents the user recently added/ingested. "
        "Answer directly and specifically using the information provided. "
        "If you can see the information in the context, provide it. "
        "Do not ask for the document again if context is provided."
    )
    
    parts: list[str] = [header]
    
    if history_text:
        parts.append("Conversation history:\n" + history_text)
    
    if retrieved_ctx:
        parts.append("Retrieved context (including recently ingested documents):\n" + retrieved_ctx)
    
    inline_ctx = "\n\n====\n\n".join(parts)[:_MAX_CONTEXT]
    query_for_agent = f"{query}\n\n----\n\n{inline_ctx}"
    
    try:
        log.info("Calling agent...")
        resp = _agent_run_with_retry(
            agent,
            query_for_agent=query_for_agent,
            retrieved_ctx=retrieved_ctx,
            session_id=session_id,
        )
        log.info("Agent call successful")
        _debug_agent_response(resp)
    except Exception as e:
        log.error(f"Agent call failed: {e}")
        ctx_preview = (inline_ctx[:800] + "…") if len(inline_ctx) > 800 else inline_ctx
        hints = (
            "\n".join(f"- {s}" for s in list(dict.fromkeys(sources))[:5]) or "(none)"
        )
        return (
            "[DEBUG] Agent call failed.\n\n"
            f"Query: {query}\n"
            f"Top sources:\n{hints}\n\n"
            f"Context preview:\n{ctx_preview}\n\n"
            f"Error: {e}"
        )
    
    out = _format_output(resp)
    has_sources = ("**Sources**" in out) or ("Sources:" in out)
    if (not has_sources) and sources:
        cleaned_sources = []
        for s in sources:
            if s.startswith('http') or 'federalregister.gov' in s or 'whitehouse.gov' in s:
                cleaned_sources.append(s)
        if cleaned_sources:
            uniq = list(dict.fromkeys(cleaned_sources))
            out = out.rstrip() + "\n\n**Sources**\n" + "\n".join(f"- {s}" for s in uniq[:5])

    if (not out or not out.strip()) and env_bool("ALLOW_GENERAL_ANSWER", True):
        log.info("Trying general answer fallback...")
        try:
            with _agent_lock:
                kwargs2 = {"query": query_for_agent}
                if session_id:
                    kwargs2["session_id"] = session_id
                try:
                    resp2 = agent.run(**kwargs2)
                except TypeError:
                    resp2 = agent.run(kwargs2)
            out2 = _format_output(resp2)
            if out2 and out2.strip():
                out = out2
                log.info("General answer fallback successful")
        except Exception as e:
            log.warning(f"General answer fallback failed: {e}")
    
    if not out or not out.strip():
        out = (
            f"Sorry, I couldn't extract a clear answer for: {query}\n\n"
            "Tip: try asking with a snippet from the document or a section heading."
        )
    
    body_only, _ = _split_sources(out)
    if session_id:
        memory.add_turn(session_id, "user", query)
        memory.add_turn(session_id, "assistant", body_only)
    
    log.info(f"Final response length: {len(out)}")
    return out