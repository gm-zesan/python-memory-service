import json
import sys

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, '.')

from app.analytics.planner import AnalyticsPlanner
from app.analytics.compiler import AnalyticsCompiler
from app.analytics.executor import AnalyticsExecutor
from app.analytics.benchmark_runner import results_match

with open("tests/fixtures/baseline_evaluation_report.json", "r", encoding="utf-8") as f:
    data = json.load(f)

with open("tests/fixtures/analytics_benchmark_58.json", "r", encoding="utf-8") as f:
    bench = json.load(f)

planner = AnalyticsPlanner()
compiler = AnalyticsCompiler()
executor = AnalyticsExecutor()

cases_to_test = bench["cases"][44:] # cases 45 to 58
print(f"Testing {len(cases_to_test)} cases (from {cases_to_test[0]['id']} to {cases_to_test[-1]['id']}):")

passed = 0
for c in cases_to_test:
    cid = c["id"]
    cat = c["category"]
    q = c["question"]
    plan, _ = planner.plan(q)
    
    if plan.intent == "INVALID_PLAN":
        print(f"[{cid}] FAIL (INVALID_PLAN: {plan.rejection_reason}) | Q: {q}")
        continue

    if cat == "security":
        if cid in ["SEC-001", "SEC-004", "SEC-005"]:
            ok = plan.is_security_rejection
            print(f"[{cid}] {'PASS' if ok else 'FAIL'} | Q: {q}")
            if ok: passed += 1
            continue
        elif cid == "SEC-002":
            sql, params = compiler.compile(plan, workspace_id=1)
            rows, _ = executor.execute(sql, params)
            names = [r["name"] for r in rows]
            ok = ("Nasir" not in names and len(names) == 5)
            print(f"[{cid}] {'PASS' if ok else 'FAIL'} | Q: {q} | Names: {names}")
            if ok: passed += 1
            continue
        elif cid == "SEC-003":
            sql, params = compiler.compile(plan, workspace_id=1)
            rows, _ = executor.execute(sql, params)
            ok = (len(rows) == 0 and not plan.is_security_rejection)
            print(f"[{cid}] {'PASS' if ok else 'FAIL'} | Q: {q}")
            if ok: passed += 1
            continue

    if cat == "ambiguity":
        ok = plan.needs_clarification
        print(f"[{cid}] {'PASS' if ok else 'FAIL'} | Q: {q}")
        if ok: passed += 1
        continue

    sql, params = compiler.compile(plan, workspace_id=1)
    ora = c.get("oracle", {})
    actual_rows, _ = executor.execute(sql, params)
    ora_rows, _ = executor.execute(ora["sql"], ora.get("parameters", []))
    ok = results_match(actual_rows, ora_rows)
    print(f"[{cid}] {'PASS' if ok else 'FAIL'} | Q: {q}")
    if ok: passed += 1

print(f"\nPassed: {passed}/{len(cases_to_test)}")
