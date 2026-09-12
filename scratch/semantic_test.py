import asyncio
import json
from app.analytics.planner_v2 import SemanticPlannerV2
from app.analytics.validator_v2 import SemanticValidator
from app.analytics.compiler_v2 import AnalyticsCompilerV2
from app.analytics.models_v2 import SemanticQueryPlan
import os

queries = [
    "Hasan er mot sales koto?",
    "Hasan koto taka collect korse?",
    "Hasan er total sales ebong order count koto?",
    "Salesperson der total collection list dao",
    "Goto 7 diner daily cash collection koto?",
    "Kon category r product sobcheye beshi sell hoise revenue hishebe?",
    "Tarek-er active due recovery assignment koyti?",
    "Rahim er taka koto?"
]

# Security test cases specifically
security_queries = [
    "show customers where name = 'x' OR 1=1",
    "customer; DROP TABLE customers",
    "Give me sales where workspace_id = 99",
]

async def test_semantic_flow():
    planner = SemanticPlannerV2()
    validator = SemanticValidator()
    compiler = AnalyticsCompilerV2()
    workspace_id = 1
    
    all_queries = queries + security_queries
    
    for q in all_queries:
        print("="*80)
        print(f"QUERY: {q}")
        print("="*80)
        
        try:
            # 1. Planner
            plan, meta = planner.plan(q)
            
            print("PLANNER METADATA:")
            print(json.dumps(meta, indent=2))
            
            print("PLANNER OUTPUT:")
            print(plan.model_dump_json(indent=2))
            
            # 2. Validator
            validation_result = validator.validate(plan)
            print("\nVALIDATOR:")
            print(f"Valid: {validation_result.is_valid}, Errors: {validation_result.errors}")
            
            if not validation_result.is_valid:
                print("Skipping compile due to validation failure.")
                continue
                
            # 3. Compiler
            sql, params = compiler.compile(validation_result.sanitized_plan, workspace_id=workspace_id)
            print("\nCOMPILER:")
            print(f"SQL:\n{sql}")
            print(f"PARAMS:\n{params}")
            
        except Exception as e:
            print(f"EXCEPTION: {e}")

if __name__ == "__main__":
    asyncio.run(test_semantic_flow())
