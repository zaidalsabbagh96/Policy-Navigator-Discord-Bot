"""
Enhanced debug test for the Policy Navigator agent.
This will help identify exactly why the agent returns empty responses.
"""

import os
import sys
import json
from pathlib import Path
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent / "src"))

load_dotenv()


def test_agent_detailed():
    """Detailed agent testing with multiple scenarios."""
    print("\n=== DETAILED AGENT TESTING ===")
    print("=" * 50)
    
    try:
        from src.agents import build_agent
        agent = build_agent()
        print(f"✓ Agent loaded: {type(agent)}")
        
        if hasattr(agent, 'id'):
            print(f"  Agent ID: {agent.id}")
        if hasattr(agent, 'name'):
            print(f"  Agent Name: {agent.name}")
        if hasattr(agent, 'tools'):
            print(f"  Agent Tools: {len(agent.tools) if agent.tools else 0}")
            if agent.tools:
                for tool in agent.tools:
                    if hasattr(tool, 'name'):
                        print(f"    - {tool.name}")
        
        print("\n--- Test 1: Simple Query (no context) ---")
        test_simple_query(agent)
        
        print("\n--- Test 2: Query with Context ---")
        test_query_with_context(agent)
        
        print("\n--- Test 3: Executive Order Query ---")
        test_executive_order_query(agent)
        
        print("\n--- Test 4: Different Parameter Formats ---")
        test_parameter_formats(agent)
        
        return True, agent
        
    except Exception as e:
        print(f"❌ Agent testing failed: {e}")
        import traceback
        traceback.print_exc()
        return False, None


def test_simple_query(agent):
    """Test a simple query without context."""
    query = "What is GDPR?"
    
    formats = [
        ("Dict with 'query'", {"query": query}),
        ("Dict with 'input'", {"input": query}),
        ("Just string", query),
        ("Dict with nested query", {"data": {"query": query}}),
    ]
    
    for format_name, params in formats:
        try:
            print(f"\nTrying format: {format_name}")
            print(f"  Params: {params if isinstance(params, dict) else f'string: {params}'}")
            
            if isinstance(params, str):
                result = agent.run(params)
            else:
                result = agent.run(params)
            
            print(f"  ✓ Call successful")
            analyze_response(result)
            
            if has_valid_output(result):
                print(f"  ✓ Valid output found with format: {format_name}")
                return
                
        except Exception as e:
            print(f"  ✗ Failed: {str(e)[:100]}")


def test_query_with_context(agent):
    """Test a query with context provided."""
    query = "What are the main principles of GDPR?"
    context = """
    The General Data Protection Regulation (GDPR) is based on several key principles:
    1. Lawfulness, fairness and transparency
    2. Purpose limitation
    3. Data minimisation
    4. Accuracy
    5. Storage limitation
    6. Integrity and confidentiality
    7. Accountability
    """
    
    formats = [
        ("Separate query and context", {
            "query": query,
            "context": context
        }),
        ("Query with embedded context", {
            "query": f"{query}\n\nContext:\n{context}"
        }),
        ("Input with context", {
            "input": query,
            "context": context
        }),
    ]
    
    for format_name, params in formats:
        try:
            print(f"\nTrying format: {format_name}")
            result = agent.run(params)
            print(f"  ✓ Call successful")
            analyze_response(result)
            
            if has_valid_output(result):
                print(f"  ✓ Valid output found with format: {format_name}")
                return
                
        except Exception as e:
            print(f"  ✗ Failed: {str(e)[:100]}")


def test_executive_order_query(agent):
    """Test the specific Executive Order query that's failing."""
    query = "Is Executive Order 14067 still in effect or has it been repealed?"
    
    context = """
    Federal Register :: Executive Orders
    
    Donald J. Trump signed 202 Executive orders in 2025.
    2025 EO 14147 - EO 14348 202
    
    Joseph R. Biden, Jr., signed 162 Executive orders between 2021 and 2025.
    2025 EO 14134 - EO 14146 13
    2024 EO 14115 - EO 14133 19
    2023 EO 14091 - EO 14114 24
    2022 EO 14062 - EO 14090 29
    2021 EO 13985 - EO 14061 77
    """
    
    formats = [
        ("Query only", {"query": query}),
        ("Query with context", {
            "query": query,
            "context": context
        }),
        ("Full formatted query", {
            "query": f"{query}\n\n---\n\nRetrieved context:\n{context}"
        }),
    ]
    
    for format_name, params in formats:
        try:
            print(f"\nTrying format: {format_name}")
            result = agent.run(params)
            print(f"  ✓ Call successful")
            analyze_response(result)
            
            if has_valid_output(result):
                print(f"  ✓ Valid output found with format: {format_name}")
                return
                
        except Exception as e:
            print(f"  ✗ Failed: {str(e)[:100]}")


def test_parameter_formats(agent):
    """Test various parameter formats to find what works."""
    query = "Tell me about data privacy regulations"
    
    test_cases = [
        ("String only", query),
        ("Dict with query", {"query": query}),
        ("Dict with input", {"input": query}),
        ("Dict with prompt", {"prompt": query}),
        ("Dict with text", {"text": query}),
        ("Dict with message", {"message": query}),
        ("Dict with question", {"question": query}),
        ("Dict with request", {"request": query}),
        ("Nested dict", {"data": {"query": query}}),
        ("Payload wrapper", {"payload": {"query": query}}),
    ]
    
    working_formats = []
    
    for format_name, params in test_cases:
        try:
            print(f"\nTrying: {format_name}")
            if isinstance(params, str):
                result = agent.run(params)
            else:
                result = agent.run(params)
            
            if has_valid_output(result):
                working_formats.append(format_name)
                print(f"  ✓ WORKING FORMAT: {format_name}")
            else:
                print(f"  ⚠ Returns empty output")
                
        except Exception as e:
            error_msg = str(e)
            if "query" in error_msg.lower():
                print(f"  ✗ Wants 'query' parameter")
            elif "input" in error_msg.lower():
                print(f"  ✗ Wants 'input' parameter")
            else:
                print(f"  ✗ Error: {error_msg[:50]}")
    
    if working_formats:
        print(f"\n✅ Working formats found: {', '.join(working_formats)}")
    else:
        print("\n❌ No working formats found!")


def analyze_response(result):
    """Analyze the structure of an agent response."""
    print(f"  Response type: {type(result)}")
    
    if hasattr(result, '__dict__'):
        attrs = list(vars(result).keys())
        print(f"  Response attributes: {attrs}")
    
    if hasattr(result, 'status'):
        print(f"  Status: {result.status}")
    
    if hasattr(result, 'data'):
        data = result.data
        print(f"  Data type: {type(data)}")
        
        if data is None:
            print(f"  Data: None")
        elif isinstance(data, str):
            print(f"  Data (string): '{data[:100]}...'")
        elif hasattr(data, '__dict__'):
            data_attrs = vars(data)
            print(f"  Data attributes: {list(data_attrs.keys())}")
            
            for field in ['output', 'input', 'text', 'message', 'content', 'result']:
                if field in data_attrs:
                    value = data_attrs[field]
                    if value is not None:
                        print(f"    {field}: {str(value)[:100]}...")
                    else:
                        print(f"    {field}: None")
            
            if 'intermediate_steps' in data_attrs:
                steps = data_attrs['intermediate_steps']
                if steps:
                    print(f"    intermediate_steps: {len(steps)} steps")
                    for i, step in enumerate(steps[:2]):
                        print(f"      Step {i}: {str(step)[:50]}...")
                else:
                    print(f"    intermediate_steps: []")
    
    for attr in ['output', 'text', 'message', 'content', 'result']:
        if hasattr(result, attr):
            value = getattr(result, attr)
            if value is not None:
                print(f"  Direct {attr}: {str(value)[:100]}...")


def has_valid_output(result):
    """Check if a result has valid output."""
    for attr in ['output', 'text', 'message', 'content']:
        value = getattr(result, attr, None)
        if value and str(value).strip():
            return True
    
    if hasattr(result, 'data') and result.data:
        data = result.data
        
        if isinstance(data, str) and data.strip():
            return True
        
        if hasattr(data, '__dict__'):
            for attr in ['output', 'text', 'message', 'content']:
                value = getattr(data, attr, None)
                if value and str(value).strip():
                    return True
        
        if isinstance(data, dict):
            for key in ['output', 'text', 'message', 'content']:
                if key in data and data[key] and str(data[key]).strip():
                    return True
    
    return False


def test_direct_api_call():
    """Test calling the aiXplain API directly to bypass any wrapper issues."""
    print("\n=== DIRECT API TEST ===")
    try:
        from aixplain.factories import AgentFactory
        
        agent_id = os.getenv("AGENT_ID")
        if not agent_id:
            print("No AGENT_ID in env, skipping direct API test")
            return
        
        print(f"Testing agent ID: {agent_id}")
        agent = AgentFactory.get(agent_id)
        
        test_query = "What is GDPR?"
        
        print(f"\nDirect call with string: '{test_query}'")
        try:
            result = agent.run(test_query)
            print(f"✓ Success!")
            analyze_response(result)
        except Exception as e:
            print(f"✗ Failed: {e}")
        
        print(f"\nDirect call with dict: {{'query': '{test_query}'}}")
        try:
            result = agent.run({"query": test_query})
            print(f"✓ Success!")
            analyze_response(result)
        except Exception as e:
            print(f"✗ Failed: {e}")
            
    except Exception as e:
        print(f"❌ Direct API test failed: {e}")


def main():
    """Run the enhanced agent tests."""
    print("🔍 Enhanced Agent Testing for Policy Navigator")
    print("=" * 70)
    
    required = ["LLM_ID", "INDEX_ID"]
    missing = [v for v in required if not os.getenv(v)]
    if missing:
        print(f"❌ Missing required env vars: {', '.join(missing)}")
        return
    
    print("✓ Environment variables loaded")
    
    try:
        from src.agents import build_agent
        from src.indexer import get_index
        print("✓ Imports successful")
    except Exception as e:
        print(f"❌ Import failed: {e}")
        return
    
    success, agent = test_agent_detailed()
    
    if not success:
        print("\n❌ Agent tests failed")
    
    test_direct_api_call()
    
    print("\n" + "=" * 70)
    print("Testing complete!")
    
    print("\n📋 RECOMMENDATIONS:")
    print("1. Check which parameter format works from the tests above")
    print("2. Update your pipeline.py to use the working format")
    print("3. Make sure your agent instructions explicitly state to return text")
    print("4. Consider recreating the agent with simpler instructions first")


if __name__ == "__main__":
    main()