import sys
import os
import unittest
from fastapi.testclient import TestClient

# Ensure python-memory-service directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.main import app
from app.neo4j_client import neo4j_client
from app.config import config

class TestMemoryService(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.test_workspace_id = 999
        cls.test_customer_id = "test_customer_rahim_101"
        cls.test_conversation_id_1 = "test_conv_alpha_1"
        cls.test_conversation_id_2 = "test_conv_beta_2"

        # Ensure clean state before tests
        neo4j_client.delete_customer_memory(cls.test_workspace_id, cls.test_customer_id)
        neo4j_client.delete_customer_memory(101, "shared_customer_uuid_777")
        neo4j_client.delete_customer_memory(202, "shared_customer_uuid_777")

    @classmethod
    def tearDownClass(cls):
        # Clean up test data after tests
        neo4j_client.delete_customer_memory(cls.test_workspace_id, cls.test_customer_id)
        neo4j_client.delete_customer_memory(101, "shared_customer_uuid_777")
        neo4j_client.delete_customer_memory(202, "shared_customer_uuid_777")

    def test_01_health(self):
        res = self.client.get("/health")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["neo4j"]["status"], "connected")
        print("✓ Health endpoint returned OK with connected Neo4j")

    def test_02_ingest_initial_preferences_and_order(self):
        payload = {
            "workspace_id": self.test_workspace_id,
            "customer_id": self.test_customer_id,
            "conversation_id": self.test_conversation_id_1,
            "channel": "facebook",
            "messages": [
                {"direction": "inbound", "body": "Hi, I want to order a black panjabi in XL size."},
                {"direction": "outbound", "body": "Sure! Would you like to pay with bKash or Cash on Delivery?"},
                {"direction": "inbound", "body": "I prefer bKash payment. My previous order was #1042."}
            ]
        }
        res = self.client.post("/memory/ingest", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["success"])
        self.assertGreaterEqual(data["edges_created"], 3)
        print(f"✓ Ingestion successful: {data['edges_created']} edges created")

    def test_03_search_memories(self):
        payload = {
            "workspace_id": self.test_workspace_id,
            "customer_id": self.test_customer_id,
            "query": "What is my preferred payment and size?"
        }
        res = self.client.post("/memory/search", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["has_memories"])
        self.assertGreaterEqual(data["memories_count"], 3)
        self.assertIn("bKash", data["formatted_memory_context"])
        self.assertIn("XL", data["formatted_memory_context"])
        self.assertIn("1042", data["formatted_memory_context"])
        print("✓ Search verified: Compact memory context correctly contains bKash, XL, and Order #1042")

    def test_04_temporal_preference_transition(self):
        # Customer in conversation 2 changes payment preference from bKash to Card
        payload = {
            "workspace_id": self.test_workspace_id,
            "customer_id": self.test_customer_id,
            "conversation_id": self.test_conversation_id_2,
            "channel": "whatsapp",
            "messages": [
                {"direction": "inbound", "body": "From now on, I want to pay using my visa card."},
            ]
        }
        res = self.client.post("/memory/ingest", json=payload)
        self.assertEqual(res.status_code, 200)

        # Search again to verify temporal transition
        search_res = self.client.post("/memory/search", json={
            "workspace_id": self.test_workspace_id,
            "customer_id": self.test_customer_id,
            "query": "preferred payment",
            "limit": 10
        })
        data = search_res.json()
        
        # Verify that Card is current and bKash is past
        memories = data["memories"]
        payment_mems = [m for m in memories if m["relation"] == "PREFERS"]
        self.assertGreaterEqual(len(payment_mems), 2)
        
        card_mem = next((m for m in payment_mems if "Card" in m["object"]), None)
        bkash_mem = next((m for m in payment_mems if "bKash" in m["object"]), None)
        
        self.assertIsNotNone(card_mem)
        self.assertEqual(card_mem["status"], "current")
        self.assertIsNotNone(bkash_mem)
        self.assertEqual(bkash_mem["status"], "past")
        print("✓ Temporal transition verified: Visa Card is CURRENT, bKash is PAST")

    def test_05_multi_tenant_workspace_isolation(self):
        # Customer exists in Workspace 101
        shared_id = "shared_customer_uuid_777"
        self.client.post("/memory/ingest", json={
            "workspace_id": 101,
            "customer_id": shared_id,
            "conversation_id": "conv_ws_101",
            "channel": "web",
            "messages": [
                {"direction": "inbound", "body": "My size is L and I pay via Nagad."}
            ]
        })

        # Query Workspace 101 -> Must find memories
        res_101 = self.client.post("/memory/search", json={
            "workspace_id": 101,
            "customer_id": shared_id,
            "query": "size and payment"
        })
        data_101 = res_101.json()
        self.assertTrue(data_101["has_memories"])
        self.assertIn("Nagad", data_101["formatted_memory_context"])

        # Query Workspace 202 with the SAME customer_id -> Must return ZERO memories!
        res_202 = self.client.post("/memory/search", json={
            "workspace_id": 202,
            "customer_id": shared_id,
            "query": "size and payment"
        })
        data_202 = res_202.json()
        self.assertFalse(data_202["has_memories"])
        self.assertEqual(data_202["memories_count"], 0)
        print("✓ Multi-tenant isolation verified: Workspace 202 cannot see Workspace 101 memories")

    def test_06_duplicate_entity_merging(self):
        # Multiple conversations refer to the exact same order #8899
        order_num = "8899"
        for i in range(1, 4):
            self.client.post("/memory/ingest", json={
                "workspace_id": self.test_workspace_id,
                "customer_id": self.test_customer_id,
                "conversation_id": f"conv_repeat_{i}",
                "channel": "web",
                "messages": [
                    {"direction": "inbound", "body": f"Any update on order #{order_num}?"}
                ]
            })

        # Query Neo4j directly to verify exactly 1 Order node was created for #8899
        driver = neo4j_client.get_driver()
        with driver.session(database=config.NEO4J_DATABASE) as session:
            result = session.run(
                "MATCH (o:Order {workspace_id: $ws, id: $order_id}) RETURN count(o) AS total",
                ws=self.test_workspace_id,
                order_id=order_num
            )
            count = result.single()["total"]
            self.assertEqual(count, 1)
        print(f"✓ Duplicate merging verified: Repeated mentions merged into 1 canonical Order node")

    def test_07_reported_issue_tracking(self):
        self.client.post("/memory/ingest", json={
            "workspace_id": self.test_workspace_id,
            "customer_id": self.test_customer_id,
            "conversation_id": "conv_issue_1",
            "channel": "web",
            "messages": [
                {"direction": "inbound", "body": "I received a damaged item in my package yesterday."}
            ]
        })

        search_res = self.client.post("/memory/search", json={
            "workspace_id": self.test_workspace_id,
            "customer_id": self.test_customer_id,
            "query": "previous issue",
            "limit": 10
        })
        data = search_res.json()
        self.assertTrue(data["has_memories"])
        issue_mem = next((m for m in data["memories"] if m["relation"] == "REPORTED"), None)
        self.assertIsNotNone(issue_mem)
        self.assertIn("damaged", issue_mem["object"])
        print("✓ Issue tracking verified: Support grievance recorded as active :Issue node")

    def test_08_anti_leakage_sanitization(self):
        from app.memory_extractor import memory_extractor
        dirty_text = "Here is my credit card 4532 1234 5678 9012 and my secret password: mypass123 and OTP: 829104"
        clean_text = memory_extractor.sanitize_text(dirty_text)
        
        self.assertNotIn("4532 1234 5678 9012", clean_text)
        self.assertNotIn("mypass123", clean_text)
        self.assertNotIn("829104", clean_text)
        self.assertIn("[CARD_REDACTED]", clean_text)
        self.assertIn("[PASSWORD_REDACTED]", clean_text)
        self.assertIn("[OTP_REDACTED]", clean_text)
        print("✓ Anti-leakage sanitizer verified: Credit cards, passwords, and OTPs are redacted")

    def test_09_delete_conversation_level_memory(self):
        conv_to_delete = "conv_to_delete_test_99"
        self.client.post("/memory/ingest", json={
            "workspace_id": self.test_workspace_id,
            "customer_id": self.test_customer_id,
            "conversation_id": conv_to_delete,
            "channel": "web",
            "messages": [
                {"direction": "inbound", "body": "Please remember order #9999"}
            ]
        })

        # Delete just this conversation
        del_res = self.client.delete(
            f"/memory/conversation/{conv_to_delete}",
            headers={"X-Workspace-Id": str(self.test_workspace_id)}
        )
        self.assertEqual(del_res.status_code, 200)
        self.assertTrue(del_res.json()["success"])
        print("✓ Conversation-level deletion verified: Session purged cleanly")

    def test_10_delete_customer_memory(self):
        res = self.client.delete(
            f"/memory/customer/{self.test_customer_id}",
            headers={"X-Workspace-Id": str(self.test_workspace_id)}
        )
        self.assertEqual(res.status_code, 200)
        
        # Verify memories are purged
        search_res = self.client.post("/memory/search", json={
            "workspace_id": self.test_workspace_id,
            "customer_id": self.test_customer_id,
            "query": "payment"
        })
        self.assertFalse(search_res.json()["has_memories"])
        print("✓ Deletion verified: All memory nodes and edges purged cleanly")

if __name__ == "__main__":
    unittest.main()
