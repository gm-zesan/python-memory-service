import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
try:
    # pyrefly: ignore [missing-import]
    from neo4j import GraphDatabase, Driver 
except ImportError:
    GraphDatabase = None
    Driver = None  # type: ignore
from .config import config

logger = logging.getLogger(__name__)

class Neo4jClient:
    def __init__(self):
        self._driver: Optional[Driver] = None

    def get_driver(self) -> Driver:
        if self._driver is None:
            self._driver = GraphDatabase.driver(
                config.NEO4J_URI,
                auth=(config.NEO4J_USER, config.NEO4J_PASSWORD),
                max_connection_lifetime=config.NEO4J_MAX_CONNECTION_LIFETIME,
                max_connection_pool_size=config.NEO4J_MAX_CONNECTION_POOL_SIZE,
            )
        return self._driver

    def close(self):
        if self._driver:
            self._driver.close()
            self._driver = None

    def health_check(self) -> Dict[str, Any]:
        try:
            driver = self.get_driver()
            with driver.session(database=config.NEO4J_DATABASE) as session:
                result = session.run("RETURN 1 AS ok, datetime() AS ts")
                record = result.single()
                return {
                    "status": "connected",
                    "timestamp": str(record["ts"]) if record else None,
                    "error": None
                }
        except Exception as e:
            logger.error(f"[Neo4jClient] Health check failed: {e}")
            return {
                "status": "disconnected",
                "error": str(e)
            }

    def upsert_customer_and_conversation(
        self,
        workspace_id: int,
        customer_id: str,
        conversation_id: str,
        channel: str = "web",
        name: Optional[str] = None,
        phone: Optional[str] = None,
        email: Optional[str] = None
    ):
        query = """
        MERGE (c:Customer {workspace_id: $workspace_id, id: $customer_id})
        ON CREATE SET 
            c.created_at = datetime(),
            c.first_seen_at = datetime(),
            c.name = $name,
            c.phone = $phone,
            c.email = $email
        ON MATCH SET
            c.last_seen_at = datetime(),
            c.name = coalesce($name, c.name),
            c.phone = coalesce($phone, c.phone),
            c.email = coalesce($email, c.email)

        MERGE (cv:Conversation {workspace_id: $workspace_id, id: $conversation_id})
        ON CREATE SET
            cv.channel = $channel,
            cv.started_at = datetime()
        ON MATCH SET
            cv.updated_at = datetime()

        MERGE (c)-[r:PARTICIPATED_IN]->(cv)
        ON CREATE SET r.occurred_at = datetime()
        """
        driver = self.get_driver()
        with driver.session(database=config.NEO4J_DATABASE) as session:
            session.run(
                query,
                workspace_id=workspace_id,
                customer_id=customer_id,
                conversation_id=conversation_id,
                channel=channel,
                name=name,
                phone=phone,
                email=email
            )

    def upsert_preference(
        self,
        workspace_id: int,
        customer_id: str,
        conversation_id: str,
        category: str,
        value: str,
        confidence: float = 1.0
    ):
        query = """
        MATCH (c:Customer {workspace_id: $workspace_id, id: $customer_id})
        OPTIONAL MATCH (c)-[old_r:HAS_PREFERENCE {status: 'current'}]->(old_pr:Preference {category: $category})
        WHERE old_pr.value <> $value
        SET old_r.status = 'past', old_r.valid_to = datetime()

        WITH c
        MERGE (pr:Preference {category: $category, value: $value})

        MERGE (c)-[r:HAS_PREFERENCE {status: 'current'}]->(pr)
        ON CREATE SET
            r.valid_from = datetime(),
            r.confidence = $confidence,
            r.source_conversation_id = $conversation_id
        ON MATCH SET
            r.last_confirmed_at = datetime(),
            r.confidence = $confidence
        """
        driver = self.get_driver()
        with driver.session(database=config.NEO4J_DATABASE) as session:
            session.run(
                query,
                workspace_id=workspace_id,
                customer_id=customer_id,
                conversation_id=conversation_id,
                category=category,
                value=value,
                confidence=confidence
            )

    def upsert_interest(
        self,
        workspace_id: int,
        customer_id: str,
        conversation_id: str,
        entity_type: str,
        entity_name: str,
        confidence: float = 1.0
    ):
        query = """
        MATCH (c:Customer {workspace_id: $workspace_id, id: $customer_id})
        MERGE (e:Entity {workspace_id: $workspace_id, type: $entity_type, name: $entity_name})

        MERGE (c)-[r:INTERESTED_IN]->(e)
        ON CREATE SET 
            r.first_expressed_at = datetime(),
            r.frequency = 1,
            r.source_conversation_id = $conversation_id,
            r.confidence = $confidence
        ON MATCH SET
            r.last_expressed_at = datetime(),
            r.frequency = r.frequency + 1,
            r.confidence = $confidence
        """
        driver = self.get_driver()
        with driver.session(database=config.NEO4J_DATABASE) as session:
            session.run(
                query,
                workspace_id=workspace_id,
                customer_id=customer_id,
                conversation_id=conversation_id,
                entity_type=entity_type,
                entity_name=entity_name,
                confidence=confidence
            )

    def upsert_issue(
        self,
        workspace_id: int,
        customer_id: str,
        conversation_id: str,
        category: str,
        description: str
    ):
        query = """
        MATCH (c:Customer {workspace_id: $workspace_id, id: $customer_id})
        CREATE (i:Issue {
            workspace_id: $workspace_id,
            id: randomUUID(),
            category: $category,
            description: $description,
            reported_at: datetime(),
            status: 'active'
        })
        CREATE (c)-[r:REPORTED_ISSUE {reported_at: datetime(), source_conversation_id: $conversation_id}]->(i)
        """
        driver = self.get_driver()
        with driver.session(database=config.NEO4J_DATABASE) as session:
            session.run(
                query,
                workspace_id=workspace_id,
                customer_id=customer_id,
                conversation_id=conversation_id,
                category=category,
                description=description
            )

    def search_customer_memories(
        self,
        workspace_id: int,
        customer_id: str,
        limit: int = 5
    ) -> List[Dict[str, Any]]:
        query = """
        MATCH (c:Customer {workspace_id: $workspace_id, id: $customer_id})
        OPTIONAL MATCH (c)-[r_pref:HAS_PREFERENCE]->(pref:Preference)
        OPTIONAL MATCH (c)-[r_int:INTERESTED_IN]->(ent:Entity)
        OPTIONAL MATCH (c)-[r_iss:REPORTED_ISSUE]->(iss:Issue)

        RETURN 
            collect(DISTINCT {type: 'preference', relation: 'HAS_PREFERENCE', category: pref.category, object: pref.value, status: r_pref.status, confidence: r_pref.confidence}) AS preferences,
            collect(DISTINCT {type: 'interest', relation: 'INTERESTED_IN', category: ent.type, object: ent.name, status: 'current', confidence: r_int.confidence}) AS interests,
            collect(DISTINCT {type: 'issue', relation: 'REPORTED_ISSUE', category: iss.category, object: iss.description, status: iss.status, confidence: 1.0}) AS issues
        """
        driver = self.get_driver()
        with driver.session(database=config.NEO4J_DATABASE) as session:
            result = session.run(query, workspace_id=workspace_id, customer_id=customer_id)
            record = result.single()
            if not record:
                return []

            memories = []
            for item in record["preferences"]:
                if item.get("object"): memories.append(item)
            for item in record["interests"]:
                if item.get("object"): memories.append(item)
            for item in record["issues"]:
                if item.get("object"): memories.append(item)

            def sort_key(m):
                return (0 if m.get("status") == "current" else 1, 0 if m.get("type") == "preference" else 1)

            memories.sort(key=sort_key)
            return memories[:limit]

    def delete_customer_memory(self, workspace_id: int, customer_id: str) -> Dict[str, int]:
        query = """
        MATCH (c:Customer {workspace_id: $workspace_id, id: $customer_id})
        OPTIONAL MATCH (c)-[r]-()
        OPTIONAL MATCH (c)-[:REPORTED_ISSUE]->(i:Issue)
        DETACH DELETE i
        DELETE r
        RETURN count(r) AS detached_edges
        """
        driver = self.get_driver()
        with driver.session(database=config.NEO4J_DATABASE) as session:
            result = session.run(query, workspace_id=workspace_id, customer_id=customer_id)
            record = result.single()
            return {"detached_edges": record["detached_edges"] if record else 0}

    def delete_conversation_memory(self, workspace_id: int, conversation_id: str) -> Dict[str, int]:
        query = """
        MATCH (cv:Conversation {workspace_id: $workspace_id, id: $conversation_id})
        OPTIONAL MATCH ()-[r {source_conversation_id: $conversation_id}]-()
        DELETE r
        DETACH DELETE cv
        RETURN count(r) AS deleted_edges
        """
        driver = self.get_driver()
        with driver.session(database=config.NEO4J_DATABASE) as session:
            result = session.run(query, workspace_id=workspace_id, conversation_id=conversation_id)
            record = result.single()
            return {"deleted_edges": record["deleted_edges"] if record else 0}

neo4j_client = Neo4jClient()
