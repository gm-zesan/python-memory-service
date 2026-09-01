# Conversation Graph Memory Service (Python + Neo4j)

A high-performance standalone Python FastAPI microservice providing **Conversation Graph Memory** for multi-channel customer support.

## Overview
- **Port**: `8002`
- **Graph DB**: Neo4j Community (Bolt port `7687`)
- **Framework**: FastAPI + Pydantic v2 + Neo4j Driver + Graphiti

## Quick Start
```bash
# 1. Activate dedicated virtual environment
source venv/bin/activate

# 2. Run unit tests
python -m unittest tests/test_memory_service.py

# 3. Start server
python main.py
```

## API Endpoints
- `GET /health`: Health check and Neo4j connectivity status
- `POST /memory/ingest`: Asynchronously parse conversation turns and commit preference/interaction edges
- `POST /memory/search`: Retrieve compact subgraphs for prompt injection (< 20ms)
- `DELETE /memory/customer/{customer_id}`: GDPR customer memory purge
- `DELETE /memory/conversation/{conversation_id}`: Remove specific conversation session memories
