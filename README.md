# Conversation Graph Memory & Semantic Analytics Service

A high-performance standalone Python FastAPI microservice providing **Conversation Graph Memory** (via Neo4j/Graphiti) and a **Semantic Text-to-SQL Analytics Engine** (via MySQL) for the Multi-Source Chatbot.

---

## 🛠️ Tech Stack & Requirements

- **Python**: `3.12+`
- **Graph Database**: Neo4j Community (Bolt port `7687`)
- **Relational Database**: MySQL (port `3306`)
- **Framework**: FastAPI + Pydantic v2
- **LLM Integrations**: OpenAI / DeepSeek / OpenRouter

---

## 🚀 Installation & Setup Guide

Follow these steps to run the service on any new PC.

### 1. Clone the Repository
Open your terminal and navigate to your desired directory, then clone the project.
```bash
cd e:\Automation
# (Ensure you have cloned the project folder here)
cd python-memory-service
```

### 2. Setup Databases (Neo4j & MySQL)
Before running this service, you need the databases up and running:

**Neo4j (Graph Database):**
The easiest way to run Neo4j is via Docker. If you have the `typesense` folder from this project suite, simply run its docker-compose file which includes Neo4j pre-configured with the APOC plugin:
```bash
cd ../typesense
docker compose up -d
```
*(This starts Neo4j on `localhost:7687` with username `neo4j` and password `secret1234`)*

**MySQL (Relational Database):**
You must have a MySQL server running (via XAMPP, Docker, or native install) on port `3306`. Ensure you have imported the main database for the `multi-source-chatbot` Laravel app, as this analytics service reads directly from it.

### 3. Create and Activate Virtual Environment
It is highly recommended to use an isolated Python virtual environment.

**For Windows (PowerShell):**
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

**For macOS/Linux:**
```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Install Dependencies
Install all required Python packages (including FastAPI, PyMySQL, Neo4j drivers, etc.).
```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables
The service requires connection details for MySQL, Neo4j, and your LLM provider.

1. Copy the example configuration file:
   ```bash
   # Windows
   copy .env.example .env
   
   # macOS/Linux
   cp .env.example .env
   ```
2. Open `.env` in a text editor and update the following critical variables:
   - **MySQL Database:** `DB_HOST`, `DB_PORT`, `DB_DATABASE`, `DB_USERNAME`, `DB_PASSWORD` (Must match your Laravel database).
   - **Neo4j Database:** `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`
   - **LLM Keys:** Set `ANALYTICS_LLM_API_KEY` or fallback keys (e.g., DeepSeek/OpenRouter).

### 5. Start the Service
Run the application using `uvicorn` (with hot-reload enabled for development).

```bash
uvicorn app.main:app --reload --port 8002 --host 0.0.0.0
```
*Alternatively, you can run `python main.py`.*

The service will now be available at: **http://127.0.0.1:8002**

---

## 📚 API Documentation

Once the server is running, you can access the interactive Swagger UI documentation at:
👉 **[http://127.0.0.1:8002/docs](http://127.0.0.1:8002/docs)**

### Key Endpoints:
- `GET /health` : Health check and database connectivity status.
- `POST /memory/ingest` : Asynchronously parse conversation turns and commit preference/interaction edges.
- `POST /memory/search` : Retrieve compact subgraphs for prompt injection.
- `DELETE /memory/customer/{customer_id}` : GDPR customer memory purge.
- `DELETE /memory/conversation/{conversation_id}` : Remove specific conversation session memories.
- **Analytics Routing**: Handles generic text-to-SQL logic for Business Intelligence.

---

## 🧪 Testing

To run the unit tests for the memory service, use the following command:
```bash
python -m unittest tests/test_memory_service.py
```
