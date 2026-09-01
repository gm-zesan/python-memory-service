import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
# pyrefly: ignore [missing-import]
from neo4j import GraphDatabase, Driver
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

    def set_payment_preference(
        self,
        workspace_id: int,
        customer_id: str,
        conversation_id: str,
        payment_code: str,
        payment_name: str
    ):
        query = """
        MATCH (c:Customer {workspace_id: $workspace_id, id: $customer_id})
        // Retire existing active payment preference if different
        OPTIONAL MATCH (c)-[old_r:PREFERS {status: 'current'}]->(old_p:PaymentMethod)
        WHERE old_p.code <> $payment_code
        SET old_r.status = 'past', old_r.valid_to = datetime()

        WITH c
        MERGE (p:PaymentMethod {code: $payment_code})
        ON CREATE SET p.name = $payment_name

        MERGE (c)-[r:PREFERS {status: 'current'}]->(p)
        ON CREATE SET 
            r.valid_from = datetime(),
            r.source_conversation_id = $conversation_id
        ON MATCH SET
            r.last_confirmed_at = datetime()
        """
        driver = self.get_driver()
        with driver.session(database=config.NEO4J_DATABASE) as session:
            session.run(
                query,
                workspace_id=workspace_id,
                customer_id=customer_id,
                conversation_id=conversation_id,
                payment_code=payment_code,
                payment_name=payment_name
            )

    def set_size_preference(
        self,
        workspace_id: int,
        customer_id: str,
        conversation_id: str,
        size_value: str,
        category_scope: str = "general",
        confidence: float = 1.0
    ):
        query = """
        MATCH (c:Customer {workspace_id: $workspace_id, id: $customer_id})
        // Retire prior size preference in same scope
        OPTIONAL MATCH (c)-[old_r:PREFERS_SIZE {status: 'current'}]->(old_pr:Preference)
        WHERE old_pr.category_scope = $category_scope AND old_pr.value <> $size_value
        SET old_r.status = 'past', old_r.valid_to = datetime()

        WITH c
        MERGE (pr:Preference {key: 'size', value: $size_value, category_scope: $category_scope})

        MERGE (c)-[r:PREFERS_SIZE {status: 'current'}]->(pr)
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
                size_value=size_value.upper(),
                category_scope=category_scope,
                confidence=confidence
            )

    def record_discussed_order(
        self,
        workspace_id: int,
        customer_id: str,
        conversation_id: str,
        order_id: str,
        reason: str = "general_inquiry"
    ):
        query = """
        MATCH (c:Customer {workspace_id: $workspace_id, id: $customer_id})
        MERGE (o:Order {workspace_id: $workspace_id, id: $order_id})
        ON CREATE SET o.first_discussed_at = datetime()

        MERGE (c)-[r:DISCUSSED]->(o)
        ON CREATE SET 
            r.reason = $reason,
            r.discussed_at = datetime(),
            r.source_conversation_id = $conversation_id
        ON MATCH SET
            r.last_discussed_at = datetime(),
            r.reason = $reason
        """
        driver = self.get_driver()
        with driver.session(database=config.NEO4J_DATABASE) as session:
            session.run(
                query,
                workspace_id=workspace_id,
                customer_id=customer_id,
                conversation_id=conversation_id,
                order_id=order_id,
                reason=reason
            )

    def record_product_interest(
        self,
        workspace_id: int,
        customer_id: str,
        conversation_id: str,
        product_title: str,
        intent_strength: str = "inquiry"
    ):
        query = """
        MATCH (c:Customer {workspace_id: $workspace_id, id: $customer_id})
        MERGE (p:Product {workspace_id: $workspace_id, title: $product_title})

        MERGE (c)-[r:INTERESTED_IN]->(p)
        ON CREATE SET 
            r.intent_strength = $intent_strength,
            r.first_expressed_at = datetime(),
            r.frequency = 1,
            r.source_conversation_id = $conversation_id
        ON MATCH SET
            r.last_expressed_at = datetime(),
            r.frequency = r.frequency + 1,
            r.intent_strength = $intent_strength
        """
        driver = self.get_driver()
        with driver.session(database=config.NEO4J_DATABASE) as session:
            session.run(
                query,
                workspace_id=workspace_id,
                customer_id=customer_id,
                conversation_id=conversation_id,
                product_title=product_title,
                intent_strength=intent_strength
            )

    def record_reported_issue(
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
        CREATE (c)-[r:REPORTED {reported_at: datetime(), source_conversation_id: $conversation_id}]->(i)
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
        OPTIONAL MATCH (c)-[r_pay:PREFERS]->(p:PaymentMethod)
        OPTIONAL MATCH (c)-[r_size:PREFERS_SIZE]->(pr:Preference)
        OPTIONAL MATCH (c)-[r_order:DISCUSSED]->(o:Order)
        OPTIONAL MATCH (c)-[r_prod:INTERESTED_IN]->(prod:Product)
        OPTIONAL MATCH (c)-[r_iss:REPORTED]->(iss:Issue)

        RETURN 
            collect(DISTINCT {type: 'preference', relation: 'PREFERS', object: p.name, code: p.code, status: r_pay.status, confidence: 1.0}) AS payment_prefs,
            collect(DISTINCT {type: 'preference', relation: 'PREFERS_SIZE', object: pr.value, scope: pr.category_scope, status: r_size.status, confidence: r_size.confidence}) AS size_prefs,
            collect(DISTINCT {type: 'historical_action', relation: 'DISCUSSED', object: o.id, reason: r_order.reason, status: 'past', confidence: 1.0}) AS discussed_orders,
            collect(DISTINCT {type: 'intent', relation: 'INTERESTED_IN', object: prod.title, strength: r_prod.intent_strength, status: 'current', confidence: 0.9}) AS interested_products,
            collect(DISTINCT {type: 'issue', relation: 'REPORTED', object: iss.category, description: iss.description, status: iss.status, confidence: 1.0}) AS reported_issues
        """
        driver = self.get_driver()
        with driver.session(database=config.NEO4J_DATABASE) as session:
            result = session.run(query, workspace_id=workspace_id, customer_id=customer_id)
            record = result.single()
            if not record:
                return []

            memories = []
            # Add payment preferences (filter out empty null objects)
            for item in record["payment_prefs"]:
                if item.get("object"):
                    memories.append(item)
            # Add size preferences
            for item in record["size_prefs"]:
                if item.get("object"):
                    memories.append(item)
            # Add discussed orders
            for item in record["discussed_orders"]:
                if item.get("object"):
                    memories.append(item)
            # Add interested products
            for item in record["interested_products"]:
                if item.get("object"):
                    memories.append(item)
            # Add issues
            for item in record["reported_issues"]:
                if item.get("object"):
                    memories.append(item)

            # Sort current preferences first, followed by recent interactions
            def sort_key(m):
                return (0 if m.get("status") == "current" else 1, 0 if m.get("type") == "preference" else 1)

            memories.sort(key=sort_key)
            return memories[:limit]

    def delete_customer_memory(self, workspace_id: int, customer_id: str) -> Dict[str, int]:
        query = """
        MATCH (c:Customer {workspace_id: $workspace_id, id: $customer_id})
        OPTIONAL MATCH (c)-[r]-()
        OPTIONAL MATCH (c)-[:REPORTED]->(i:Issue)
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
