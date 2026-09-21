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
The easiest way to run Neo4j is via Docker. Run the following command in your terminal to start a Neo4j instance with the required APOC plugin enabled:
```bash
docker run -d --name neo4j \
  -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/secret1234 \
  -e NEO4J_PLUGINS=\[\"apoc\"\] \
  neo4j:5-community
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

### 4. Install Dependencies
Install all required Python packages (including FastAPI, PyMySQL, Neo4j drivers, etc.).
```bash
pip install -r requirements.txt
```

### 5. Configure Environment Variables
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

### 6. Start the Service
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

### ⚙️ System Endpoints

- **`GET /health`**
  - **Description:** Checks the health and connectivity of the service and the Neo4j database. Use this to monitor if the service is running perfectly.

### 📊 Analytics Endpoints (Business Intelligence)

- **`POST /analytics/query`**
  - **Description:** The core Semantic Analytics Engine (Text-to-SQL). It takes a natural language query in English or Bengali, translates it into a semantic query plan using an LLM, compiles it into a safe read-only SQL query, executes it against the database, and returns a formatted markdown report.

### 🧠 Memory Graph Endpoints (Customer Knowledge)

- **`POST /memory/ingest`**
  - **Description:** Analyzes a conversation session (customer and agent messages) using an LLM to extract important facts, preferences, interests, and issues. It then saves these extracted entities and relationships as a knowledge graph in the Neo4j database.
  
- **`POST /memory/search`**
  - **Description:** Searches the Neo4j knowledge graph for relevant past memories and preferences of a specific customer based on their current query. It returns a compact sub-graph context that can be injected into an external LLM's system prompt for personalized responses.

- **`GET /memory/customer/{customer_id}`**
  - **Description:** Fetches the entire memory graph (nodes and edges) associated with a specific customer for viewing or administrative purposes.

- **`DELETE /memory/customer/{customer_id}`**
  - **Description:** Completely deletes all stored memories, preferences, and issues for a specific customer from the Neo4j database (Useful for GDPR compliance or resetting a customer profile).

- **`DELETE /memory/conversation/{conversation_id}`**
  - **Description:** Deletes memories associated with a specific conversation session. Useful if a conversation was recorded by mistake or contains sensitive information that needs to be purged.

---

## 🧪 Testing

To run the unit tests for the memory service, use the following command:
```bash
python -m unittest tests/test_memory_service.py
```
