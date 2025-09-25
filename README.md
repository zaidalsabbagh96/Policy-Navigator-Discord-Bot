# Policy Navigator Agent
**A Multi-Agent RAG System for Government Regulation Search**

## Overview

Policy Navigator is an intelligent Discord bot powered by aiXplain's agentic RAG system that helps users query and extract insights from complex government regulations, compliance policies, and public health guidelines. The system combines vector search, web scraping, and external API integration to provide accurate, source-referenced answers to policy questions.

## What the Agent Does

The Policy Navigator agent can:

- **Extract specific information** from policy documents (Executive Orders, regulations, compliance documents)
- **Search through indexed datasets** of GDPR violations, AI governance documents, and government data
- **Scrape government websites** for real-time policy information
- **Provide structured answers** with source references and JSON data when requested
- **Handle document uploads** and URL ingestion through Discord commands
- **Maintain conversation context** for follow-up questions

### Example Capabilities

**Policy Status Checking:**
```
User: "Is Executive Order 14067 still in effect or has it been repealed?"
Agent: "Executive Order 14067 has been explicitly revoked by Executive Order 14178, meaning it is no longer in effect."
```

**GDPR Violation Analysis:**
```
User: "What are the main GDPR violation types and their average fines?"
Agent: "Based on the indexed violations data, the main types include non-compliance with lawful basis for data processing (avg €15,000), information security failures (avg €45,000), and data breach notifications (avg €8,500)."
```

## Architecture

The system implements a **single-agent architecture** with the following components:

### Core Components

1. **RAG Pipeline** (`src/pipeline.py`) - Orchestrates retrieval and response generation
2. **Vector Index** (`src/indexer.py`) - Manages document embeddings and semantic search
3. **Data Ingestion** (`src/ingest.py`) - Handles file uploads, web scraping, and data processing
4. **Agent Configuration** (`src/agents.py`) - Defines the Policy Navigator agent with tools
5. **Memory Management** (`src/memory.py`) - Maintains conversation context
6. **Discord Interface** (`bot.py`) - Provides user interaction through Discord commands

### Tool Integration

The agent integrates **three types of tools**:

1. **Marketplace Tool**: Tavily Search API for external web search and verification
2. **Custom Web Scraping Tool**: Extracts content from government websites
3. **SQL/Database Tool**: PostgreSQL integration for structured data queries

## Setup Instructions

### Prerequisites

- Python 3.8+
- aiXplain API key
- Discord Bot Token
- Kaggle API credentials (optional, for additional datasets)

### Installation

1. **Clone the repository:**
```bash
git clone https://github.com/zaidalsabbagh96/Policy-Navigator-Discord-Bot.git
cd Policy-Navigator-Discord-Bot
```

2. **Install dependencies:**
```bash
pip install -r requirements.txt
```

3. **Configure environment variables:**
Create a `.env` file with the following:

```env
# aiXplain Configuration
AIXPLAIN_API_KEY=your_aixplain_api_key_here
INDEX_ID=your_index_id_here
AGENT_ID=your_agent_id_here
DEPLOY_AGENT=true
LLM_ID=your_llm_model_id_here

# Tool IDs (marketplace tools)
SEARCH_TOOL_ID=6736411cf127849667606689
SCRAPER_TOOL_ID=66f423426eb563fa213a3531
POSTGRES_TOOL_ID=684ae26dcee3bec0fdfe26d6

# Data Configuration
DATA_DIR=./data
USE_WEB_BACKFILL=false
ALLOW_GENERAL_ANSWER=true
SEED_URL=https://www.federalregister.gov/executive-orders

# Discord Bot Configuration
DISCORD_TOKEN=your_discord_bot_token
GUILD_ID=your_guild_id_optional
```

4. **Run the bot:**
```bash
python bot.py
```

## Data Sources

The system is pre-configured with knowledge from multiple data sources:

### Dataset Sources
1. **GDPR Violations Dataset** (Kaggle: jessemostipak/gdpr-violations)
   - 437 records of GDPR violations with fines, authorities, and violation types
2. **AI Governance Documents** (Kaggle: umerhaddii/ai-governance-documents-data)
   - Comprehensive collection of AI policy documents and guidelines

### Website Sources
- **Federal Register** - Executive Orders and federal regulations
- **Government policy websites** (configurable via SEED_URL)

## Usage

### Discord Commands

**Ask Questions:**
```
/ask query: "What are the compliance requirements for small businesses under GDPR?"
!ask Is Executive Order 14067 still active?
```

**Add Data Sources:**
```
/add url: https://www.whitehouse.gov/briefing-room/presidential-actions/
/add file: [upload a policy document]
```

**Reset Conversation:**
```
/reset_history
```

### Example Inputs/Outputs

**Input:** `/ask What was the highest GDPR fine in 2019?`

**Output:**
```
Executive Orders: What was the highest GDPR fine in 2019?

The highest GDPR fine in 2019 was €50,000,000 imposed by the French data protection authority (CNIL) on Google LLC for transparency and consent violations under Articles 12, 13, and 7 of GDPR.

Sources
• kaggle:gdpr_violations dataset
• https://www.cnil.fr/en/cnils-restricted-committee-imposes-financial-penalty-50-million-euros-against-google-llc
```

**Input:** `/ask query: "When was Executive Order 14067 signed?"`

**Output:**
```
Executive Order 14067 was signed on March 9, 2022, by President Biden, titled "Ensuring Responsible Development of Digital Assets."

```json
{"eo_number":"EO 14067","signing_date":"March 9, 2022","title":"Ensuring Responsible Development of Digital Assets"}
```

Sources
• https://www.federalregister.gov/executive-orders
```
```
## Technical Implementation

### Vector Storage
The system uses aiXplain's vector index for semantic search over policy documents. Documents are chunked, embedded, and stored with metadata for efficient retrieval.

### Error Handling & Logging
- Comprehensive error handling in all pipeline components
- Detailed logging via `src/utils.py` for debugging and monitoring
- Graceful fallbacks when external APIs are unavailable

### Memory & Context
- Session-based conversation memory for follow-up questions
- Recent document ingestion tracking for contextual responses
- Automatic context injection from recently uploaded documents

## Development

### Project Structure
```
Policy-Navigator-Discord-Bot/
├── src/
│   ├── agents.py          # Agent configuration and tools
│   ├── pipeline.py        # RAG pipeline orchestration
│   ├── indexer.py         # Vector index management
│   ├── ingest.py          # Data ingestion and processing
│   ├── memory.py          # Conversation memory
│   └── utils.py           # Logging and utilities
├── notebooks/
│   └── notes.ipynb        # Development and testing notebook
├── bot.py                 # Discord bot interface
├── requirements.txt       # Python dependencies
└── .env.example          # Environment configuration template
```

### Extending the System

To add new data sources:

1. **For URLs**: Use the `/add url:` command or modify `WEB_URLS` in the ingestion pipeline
2. **For datasets**: Add CSV processing in `src/ingest.py` following the existing patterns
3. **For APIs**: Extend tool integration in `src/agents.py`

## Future Improvements

### Planned Enhancements

**Enhanced Detail Control**
   - **Details Parameter**: Add `details: true` option to Discord commands for comprehensive responses
   - **Rich Context**: Detailed responses include source citations, regulatory context, and related policy connections
   - **Implementation Guidance**: Provide actionable steps for compliance and policy implementation
   - **Cross-Reference Analysis**: Show connections between related policies, amendments, and court cases

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Acknowledgments

- Built with [aiXplain](https://aixplain.com/) SDK for agentic AI capabilities
- Policy datasets from [Kaggle](https://kaggle.com/)
- Government data from [Federal Register](https://www.federalregister.gov/)

## Contact

For questions or issues, please open a GitHub issue or contact me directly via linkedin or gmail
- Gmail: sabbaghzaid88@gmail.com
- linkedin: https://www.linkedin.com/in/zaid-sabbagh-6a7287227/
---

**Note**: This project was developed as part of the aiXplain Certification Course Project for building multi-agent RAG systems.
