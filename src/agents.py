from src.utils import env, env_bool, log

def build_agent():
    return build_team_agent() if env_bool("USE_TEAM_AGENT", False) else build_single_agent()

def build_single_agent():
    from aixplain.factories import AgentFactory
    llm_id = env("LLM_ID")
    log.info("Building single aiXplain agent...")
    return AgentFactory.create(
        name="Policy Navigator (Single)",
        description="RAG agent for regulations with web+dataset ingestion.",
        instructions="Use retrieved sources and include brief citations.",
        tools=[],
        llm_id=llm_id,
    )

def build_team_agent():
    try:
        from aixplain.factories import TeamAgentFactory as Factory
    except Exception:
        from aixplain.factories import AgentFactory as Factory

    from aixplain.factories import AgentFactory
    use_mentalist = env_bool("USE_MENTALIST", True)
    llm_id = env("LLM_ID")

    # Sub-agents: you can attach tools to either of these later
    retriever = AgentFactory.create(
        name="Retriever",
        description="Find and return relevant policy passages only.",
        instructions="Return the most relevant chunks and brief citations. No prose.",
    )
    analyst = AgentFactory.create(
        name="Analyst",
        description="Synthesize grounded answers with citations.",
        instructions="Use retrieved chunks to answer clearly. Include citations.",
    )

    log.info(f"Building team agent (mentalist={use_mentalist})...")
    team = Factory.create(
        name="Policy Navigator (Team)",
        description="Retriever→Analyst with Mentalist planning.",
        agents=[retriever, analyst],
        llm_id=llm_id,
        use_mentalist=use_mentalist,
        use_inspector=False
    )
    team.deploy()
    return team
