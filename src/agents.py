from __future__ import annotations

import json
from typing import Optional

from src.utils import env, env_bool, log

from aixplain.factories import AgentFactory, ModelFactory

LLM_ID = env("LLM_ID", required=True)

SEARCH_TOOL_ID = env("SEARCH_TOOL_ID") or "6736411cf127849667606689"
SCRAPER_TOOL_ID = env("SCRAPER_TOOL_ID") or "66f423426eb563fa213a3531"
POSTGRES_TOOL_ID = env("POSTGRES_TOOL_ID") or "684ae26dcee3bec0fdfe26d6"


def _load_params(name: str, fallback: dict) -> dict:
    raw = env(name)
    if not raw:
        return dict(fallback)
    try:
        return json.loads(raw)
    except Exception:
        return dict(fallback)


SEARCH_PARAMS = _load_params("SEARCH_TOOL_PARAMS", {"numResults": 7})
SCRAPER_PARAMS = _load_params("WEBREADER_TOOL_PARAMS", {"max_pages": 1})

AGENT_NAME = env("AGENT_NAME") or "Policy Navigator v4"
DEPLOY = env_bool("DEPLOY_AGENT", True)

EXISTING_AGENT_ID: Optional[str] = env("AGENT_ID")

tools = []

try:
    search_model = ModelFactory.get(SEARCH_TOOL_ID)
    search_tool = AgentFactory.create_model_tool(
        model=search_model,
        description="Web search. Use only when the provided 'Retrieved context' is insufficient.",
    )
    tools.append(search_tool)
    log.info("Attached tool: Tavily Search")
except Exception as e:
    log.warning(f"Could not attach Tavily Search tool: {e}")

try:
    scrape_model = ModelFactory.get(SCRAPER_TOOL_ID)
    scrape_tool = AgentFactory.create_model_tool(
        model=scrape_model,
        description="Fetch and read webpages when a specific URL is known or discoverable from context. Do not call this tool with plain text; only call with a valid URL.",
    )
    tools.append(scrape_tool)
    log.info("Attached tool: Scrape Website")
except Exception as e:
    log.warning(f"Could not attach Scrape Website tool: {e}")

try:
    pg_model = ModelFactory.get(POSTGRES_TOOL_ID)
    pg_tool = AgentFactory.create_model_tool(
        model=pg_model, description="Execute SQL against the 'customers' table."
    )
    tools.append(pg_tool)
    log.info("Attached tool: Postgres Query")
except Exception as e:
    log.warning(f"Could not attach Postgres tool: {e}")

instructions = """
You are **Policy Navigator**, an expert at extracting and answering questions from government regulations and policy documents.

## CRITICAL RULES

1. **ALWAYS READ THE PROVIDED CONTEXT FIRST**
   - The "Retrieved context" section contains the actual document content
   - Look for key information like EO numbers, dates, titles, and quoted text
   - The context often contains exactly what the user is asking for

2. **EXTRACT INFORMATION DIRECTLY FROM CONTEXT**
   - If you see "EO Citation EO 14067" in the context, that's the EO number
   - If you see "Signing Date March 9, 2022" in the context, that's the signing date
   - If you see document titles or quoted passages, extract them exactly

3. **NEVER ASK FOR DOCUMENTS THAT ARE ALREADY PROVIDED**
   - If there is ANY context provided, use it to answer
   - Do NOT say "provide the document" when context exists
   - The user has already ingested documents — they appear in the context

## How to Process Queries

When you receive a query with "Retrieved context":
1. Carefully scan the context for the requested information
2. Look for patterns like:
   - "EO Citation EO [number]" for Executive Order numbers
   - "Signing Date [date]" for signing dates
   - "Title:" or document headers for titles
   - Direct quotes matching what the user requests
3. Extract and return the specific information found
4. If truly not in context, say what specific information is missing

## Common Information Patterns

Executive Orders typically appear as:
- EO Citation: EO [number]
- Signing Date: [Month Day, Year]
- President: [Name]
- Document Number: [Year-Number]
- Publication Date: [Date]

## Output Format

- Start with the direct answer, concise and factual.
- For Executive Orders, use:
  - **EO Number**: EO [number]
  - **Signing Date**: [date]
  - **Title**: [full title]
  - **Quoted text**: "[exact quote]" (if requested)
- Do **not** include headings named "Sources" or "Details" in your output.
- When the question asks for specific fields (e.g., EO number, signing date, title, agencies, quotes), after the concise prose answer also include a compact JSON object with those fields if available, fenced as:

```json
{"eo_number":"EO 14067","signing_date":"March 9, 2022","title":"Ensuring Responsible Development of Digital Assets","quote":"By the authority vested..."}
```

Return the prose first, then the JSON block. Keep both brief and accurate.

## Tool Usage

Only use web search or scrape tools if:
* The retrieved context is completely empty
* The user explicitly asks to search for something new
* You need additional information not in the context

Remember: The context contains the documents the user has already added. Read it carefully and extract the answers from there.
""".strip()

if EXISTING_AGENT_ID:
    log.info(f"Loading existing agent: {EXISTING_AGENT_ID}")
    agent = AgentFactory.get(EXISTING_AGENT_ID)
else:
    log.info("Creating Policy Navigator agent with 3 tools…")
    agent = AgentFactory.create(
        name=AGENT_NAME,
        description="Extracts specific information from policy documents and regulations using the provided context.",
        instructions=instructions.strip(),
        tools=tools,
        llm_id=LLM_ID,
    )

if DEPLOY:
    try:
        agent.deploy()
        log.info(
            f"Agent deployed. Save this AGENT_ID in .env: {getattr(agent, 'id', '(unknown)')}"
        )
    except Exception as e:
        log.warning(f"Agent deploy failed (continuing locally): {e}")


def build_agent():
    return agent
