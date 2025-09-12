# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is an AI-powered financial reporter system that analyzes company financial data from Korean DART (Data Analysis, Retrieval and Transfer System) and generates comprehensive investment reports. The system combines multiple AI agents to process earnings reports, financial statements, IR presentations, and business documents.

## Core Architecture

### Main Components

- **`src/report.py`** - Main orchestration script that coordinates the entire reporting pipeline
- **`src/deep_agent.py`** - LangGraph-based deep research agent for earnings analysis and scenario generation  
- **`src/readPDF_v2.py`** - PDF reader utility for processing financial documents

### Key Tools (`src/tools/`)

- **`agents.py`** - Generic Agent class wrapper for OpenAI API calls
- **`summarizer.py`** - Hierarchical text summarization using token-aware chunking
- **`pdf_parser.py`** - Advanced PDF parser that converts pages to images and uses GPT-4V for analysis
- **`table_parser.py`** - Table extraction and processing utilities

## Dependencies and Setup

### Required External Tools
Before running the project, install these external dependencies (documented in `install_process.txt`):

```bash
# Install unstructured with all document support
pip install "unstructured[all-docs]"

# Windows-specific: Install poppler for PDF processing
# Download from: https://github.com/oschwartz10612/poppler-windows/releases/

# Install tesseract for OCR
# Download from: https://github.com/UB-Mannheim/tesseract/wiki

# Install libmagic
pip install python-magic
```

### Python Dependencies
Install Python packages from `requirements.txt`:
```bash
pip install -r requirements.txt
```

### Configuration File
The system expects a config file at `D:/config.ini` with:
```ini
[dart]
API_KEY = your_dart_api_key

[openai] 
API_KEY = your_openai_api_key

[tavily]
API_KEY_NH = your_tavily_api_key
```

## Common Commands

### Running Analysis
```bash
# Run complete financial analysis pipeline
python src/report.py

# Run deep research agent with scenario generation
python src/deep_agent.py

# Parse PDF IR documents
python src/tools/pdf_parser.py --pdf path/to/document.pdf --out ./output
```

### Data Structure
The system expects this data structure:
```
./data/
├── A{company_code}_IS.xlsx    # Financial statements (consensus, sales, op, income sheets)
├── A{company_code}_IR.pdf     # IR presentation PDF
└── summary/                   # Generated markdown summaries
    ├── company_business.md
    ├── financial_analysis.md
    ├── earnings_analysis.md
    └── ir_summary.md
```

## Key Integration Points

### Agent Workflow
1. **Data Collection**: `report.py` fetches DART reports, financial data, and IR documents
2. **Processing**: Each component (business summary, financial analysis, earnings analysis, IR summary) is processed separately
3. **Deep Analysis**: `deep_agent.py` takes processed summaries and generates scenarios using LangGraph workflow
4. **Output**: Final markdown reports with charts and scenario analysis

### AI Model Configuration
- Default model: `gpt-4.1-nano-2025-04-14` (configurable in agent classes)
- PDF analysis uses: `gpt-4o-mini` for vision tasks
- Summarizer uses token-aware chunking with 4000 token chunks, 2000 token summaries

### Chart Generation
The system includes a sophisticated chart generation tool (`make_chart`) that supports:
- Multiple chart types (bar, line, pie, scatter, area)
- Multi-series data with secondary y-axis
- Data labels and customizable styling

## Important Notes

- Company code is hardcoded as '381970' in `report.py` - modify as needed
- The system processes Korean financial documents and generates Korean language reports
- PDF parsing can handle both text extraction and vision-based analysis for complex layouts
- The deep agent supports human-in-the-loop approval workflows (currently disabled in test mode)