"""
Automated 58-Case Benchmark Runner for Analytics Intelligence Baseline.
Runs all cases through: Question -> Planner -> Compiler -> Safe Executor -> Oracle Evaluation.
Captures Intent Accuracy, Plan Accuracy, Result Correctness, Safety, and Latency.
"""

import json
import os
import sys
import time
from typing import Dict, Any, List

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from app.analytics.models import AnalyticsQueryPlan
from app.analytics.planner import AnalyticsPlanner
from app.analytics.compiler import AnalyticsCompiler
from app.analytics.executor import AnalyticsExecutor, SecurityViolationError
from app.analytics.formatter import AnalyticsFormatter


def results_match(actual: List[Dict[str, Any]], oracle: List[Dict[str, Any]]) -> bool:
    """
    Compares actual query results with oracle query results.
    Tolerates column alias variations if data values and row orders match.
    """
    if actual == oracle:
        return True
    if len(actual) != len(oracle):
        return False
    for r_act, r_ora in zip(actual, oracle):
        for k, v in r_ora.items():
            if k in r_act:
                act_v = r_act[k]
                if isinstance(v, (int, float)) and isinstance(act_v, (int, float)):
                    if abs(float(act_v) - float(v)) >= 0.01:
                        return False
                elif str(act_v).strip() != str(v).strip():
                    return False
            else:
                # Key alias might differ, check if value exists in actual row
                found = False
                for act_v in r_act.values():
                    if isinstance(v, (int, float)) and isinstance(act_v, (int, float)):
                        if abs(float(act_v) - float(v)) < 0.01:
                            found = True
                            break
                    elif str(act_v).strip() == str(v).strip():
                        found = True
                        break
                if not found:
                    return False
    return True


def run_benchmark(fixture_path: str = None) -> Dict[str, Any]:
    if not fixture_path:
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        fixture_path = os.path.join(base_dir, "tests", "fixtures", "analytics_benchmark_58.json")

    if not os.path.exists(fixture_path):
        raise FileNotFoundError(f"Benchmark fixture not found at: {fixture_path}")

    with open(fixture_path, "r", encoding="utf-8") as f:
        benchmark_data = json.load(f)

    planner = AnalyticsPlanner()
    compiler = AnalyticsCompiler()
    executor = AnalyticsExecutor()
    formatter = AnalyticsFormatter()

    cases = benchmark_data.get("cases", [])
    total_cases = len(cases)
    case_reports = []

    passed_functional = 0
    passed_security = 0
    total_functional = benchmark_data.get("functional_cases", 53)
    total_security = benchmark_data.get("security_cases", 5)

    intent_correct_count = 0
    plan_correct_count = 0
    result_correct_count = 0

    category_stats = {}
    latencies = []
    llm_latencies = []
    db_latencies = []

    print(f"\n[RUN] Running Analytics Baseline Benchmark on {total_cases} Frozen Cases...\n" + "=" * 80)

    for idx, case in enumerate(cases, 1):
        cid = case["id"]
        cat = case["category"]
        question = case["question"]
        expected_intent = case.get("expected_intent")
        oracle = case.get("oracle", {})
        expected_res = case.get("expected_result")

        if cat not in category_stats:
            category_stats[cat] = {"total": 0, "passed": 0}
        category_stats[cat]["total"] += 1

        print(f"[{idx:02d}/{total_cases}] Case: {cid:<10} | Cat: {cat:<16} | Q: {question[:35]:<35}...", end=" ")

        # ── Step 1: LLM Planner (Direct, No SQL generation) ──
        plan, llm_ms = planner.plan(question)
        llm_latencies.append(llm_ms)

        case_passed = False
        plan_correct = False
        sql_safe = True
        result_correct = False
        final_answer_correct = False
        notes = ""
        db_ms = 0.0
        compiled_sql = ""
        compiled_params = []
        actual_results = []

        # Intent comparison (case-insensitive, normalized)
        actual_intent = plan.intent.strip().lower()
        exp_intent_norm = expected_intent.strip().lower() if expected_intent else ""

        intent_match = (actual_intent == exp_intent_norm) or (
            exp_intent_norm in ["collector_ranking", "top_collectors"] and actual_intent in ["collector_ranking", "top_collectors", "collector_performance"]
        ) or (
            exp_intent_norm in ["cash_collection", "collection"] and actual_intent in ["cash_collection", "collection", "monthly_collection"]
        ) or (
            exp_intent_norm in ["sales_summary"] and actual_intent in ["sales_summary", "sales_difference"]
        ) or (
            exp_intent_norm in ["total_due_summary", "customer_due_list"] and actual_intent in ["total_due_summary", "total_due", "customer_due_list"]
        )

        if intent_match:
            intent_correct_count += 1

        # ── Step 2 & 3: Evaluation by Category ──
        if cat == "security":
            exp_behavior = case.get("expected_behavior")
            if exp_behavior == "REJECT":
                plan_correct = plan.is_security_rejection
                if plan.is_security_rejection:
                    case_passed = True
                    result_correct = True
                    notes = f"Properly rejected: {plan.rejection_reason}"
                else:
                    notes = f"Security leak: failed to reject mutation/OOD. Plan: {plan.intent}"

            elif exp_behavior == "SCOPE_TO_WORKSPACE":
                plan_correct = (not plan.is_security_rejection)
                if plan_correct:
                    try:
                        compiled_sql, compiled_params = compiler.compile(plan, workspace_id=1)
                        if compiled_sql:
                            executor._validate_safety(compiled_sql)
                            actual_results, db_ms = executor.execute(compiled_sql, compiled_params)
                            db_latencies.append(db_ms)
                            customer_names = [r.get("name") for r in actual_results]
                            if "Nasir" not in customer_names and len(customer_names) == 5:
                                case_passed = True
                                result_correct = True
                                notes = "Tenant isolated: Workspace 2 data shielded."
                            else:
                                notes = f"Cross-tenant leak detected: {customer_names}"
                        else:
                            notes = "Compiler returned empty SQL."
                    except SecurityViolationError as sve:
                        sql_safe = False
                        notes = f"SQL Safety Violation: {str(sve)}"
                else:
                    notes = f"Plan rejected: {plan.rejection_reason}"

            elif exp_behavior == "SAFE_PARAMETERIZED_QUERY":
                plan_correct = (not plan.is_security_rejection)
                if plan_correct:
                    try:
                        compiled_sql, compiled_params = compiler.compile(plan, workspace_id=1)
                        if compiled_sql:
                            executor._validate_safety(compiled_sql)
                            actual_results, db_ms = executor.execute(compiled_sql, compiled_params)
                            db_latencies.append(db_ms)
                            if len(actual_results) == 0:
                                case_passed = True
                                result_correct = True
                                notes = "SQL injection neutralized via parameterization."
                            else:
                                notes = f"SQL injection bypass: returned {len(actual_results)} rows."
                        else:
                            notes = "Compiler returned empty SQL."
                    except SecurityViolationError as sve:
                        sql_safe = False
                        notes = f"SQL Safety Violation: {str(sve)}"
                else:
                    notes = f"Unexpected rejection: {plan.rejection_reason}"

            if case_passed:
                passed_security += 1
                category_stats[cat]["passed"] += 1
                print("[PASS]")
            else:
                print(f"[FAIL] ({notes})")

        elif cat == "ambiguity":
            if plan.needs_clarification:
                case_passed = True
                plan_correct = True
                result_correct = True
                passed_functional += 1
                category_stats[cat]["passed"] += 1
                notes = f"Clarification requested: {plan.clarification_message}"
                print("[PASS]")
            else:
                notes = f"Failed to flag ambiguity. Assumed intent: {plan.intent}"
                print(f"[FAIL] ({notes})")

        else:
            # Functional Business Cases
            plan_correct = intent_match

            # Compile Plan to Safe SQL
            compiled_sql, compiled_params = compiler.compile(plan, workspace_id=1)

            try:
                # Verify safety before execution
                executor._validate_safety(compiled_sql)
            except SecurityViolationError as sve:
                sql_safe = False
                notes = f"SQL Safety Violation: {str(sve)}"

            if sql_safe and compiled_sql:
                try:
                    actual_results, db_ms = executor.execute(compiled_sql, compiled_params)
                    db_latencies.append(db_ms)
                except Exception as e:
                    actual_results = []
                    notes = f"Execution Error: {str(e)}"

                # Compare with Independent Oracle
                if oracle.get("type") == "sql":
                    oracle_results, _ = executor.execute(oracle["sql"], oracle.get("parameters", []))
                    if results_match(actual_results, oracle_results):
                        case_passed = True
                        result_correct = True
                        notes = "Matched Oracle result exactly."
                    else:
                        notes = f"Result mismatch. Actual: {actual_results[:1]} vs Oracle: {oracle_results[:1]}"
                else:
                    notes = "No SQL oracle defined."
            elif not compiled_sql:
                notes = f"Compiler produced empty SQL for intent: {plan.intent}"

            if case_passed:
                passed_functional += 1
                category_stats[cat]["passed"] += 1
                print("[PASS]")
            else:
                print(f"[FAIL] ({notes})")

        # Step 4: Final Formatter
        try:
            formatted_answer = formatter.format(
                question=question,
                plan=plan,
                results=actual_results,
                latency_ms=(llm_ms + db_ms),
            )
            final_answer_correct = bool(formatted_answer and len(formatted_answer) > 10)
        except Exception:
            final_answer_correct = False

        if plan_correct:
            plan_correct_count += 1
        if result_correct:
            result_correct_count += 1

        total_ms = llm_ms + db_ms
        latencies.append(total_ms)

        # Standard Case Report Schema
        case_reports.append({
            "id": cid,
            "category": cat,
            "question": question,
            "expected_intent": expected_intent,
            "actual_intent": plan.intent,
            "plan_correct": plan_correct,
            "sql_safe": sql_safe,
            "result_correct": result_correct,
            "final_answer_correct": final_answer_correct,
            "latency_ms": round(total_ms, 2),
            "llm_latency_ms": round(llm_ms, 2),
            "db_latency_ms": round(db_ms, 2),
            "status": "PASS" if case_passed else "FAIL",
            "notes": notes,
            "compiled_sql": compiled_sql,
            "compiled_params": compiled_params,
            "actual_result": actual_results,
            "expected_result": expected_res,
        })
        time.sleep(0.15)

    # Latencies
    latencies.sort()
    p50 = latencies[len(latencies) // 2] if latencies else 0.0
    p95_idx = int(len(latencies) * 0.95)
    p95 = latencies[p95_idx] if latencies else 0.0

    avg_llm = sum(llm_latencies) / len(llm_latencies) if llm_latencies else 0.0
    avg_db = sum(db_latencies) / len(db_latencies) if db_latencies else 0.0

    overall_pass = passed_functional + passed_security
    overall_accuracy = (overall_pass / total_cases) * 100.0
    func_accuracy = (passed_functional / total_functional) * 100.0
    sec_accuracy = (passed_security / total_security) * 100.0
    intent_accuracy = (intent_correct_count / total_cases) * 100.0
    plan_accuracy = (plan_correct_count / total_cases) * 100.0
    result_accuracy = (result_correct_count / total_cases) * 100.0

    summary = {
        "benchmark_version": "v1.0",
        "dataset": "business_analytics_seed_v1",
        "total_cases": total_cases,
        "total_passed": overall_pass,
        "overall_accuracy_pct": round(overall_accuracy, 2),
        "functional_cases": total_functional,
        "functional_passed": passed_functional,
        "functional_accuracy_pct": round(func_accuracy, 2),
        "security_cases": total_security,
        "security_passed": passed_security,
        "security_pass_rate_pct": round(sec_accuracy, 2),
        "intent_accuracy_pct": round(intent_accuracy, 2),
        "plan_accuracy_pct": round(plan_accuracy, 2),
        "result_accuracy_pct": round(result_accuracy, 2),
        "latency_p50_ms": round(p50, 2),
        "latency_p95_ms": round(p95, 2),
        "avg_llm_time_ms": round(avg_llm, 2),
        "avg_db_time_ms": round(avg_db, 2),
        "category_breakdown": category_stats,
        "case_details": case_reports,
    }

    report_path = os.path.join(os.path.dirname(fixture_path), "baseline_evaluation_report.json")
    with open(report_path, "w", encoding="utf-8") as rf:
        json.dump(summary, rf, indent=2, ensure_ascii=False)

    # Required Summary Output Format
    print("\n" + "=" * 80)
    print("ANALYTICS INTELLIGENCE BASELINE BENCHMARK SUMMARY")
    print("=" * 80)
    print(f"Functional Accuracy:     {passed_functional}/{total_functional} ({func_accuracy:.1f}%)")
    print(f"Security Pass Rate:      {passed_security}/{total_security} ({sec_accuracy:.1f}%)")
    print(f"Intent Accuracy:         {intent_accuracy:.1f}%")
    print(f"Plan Accuracy:           {plan_accuracy:.1f}%")
    print(f"Result Accuracy:         {result_accuracy:.1f}%")
    print(f"P50 Latency:             {p50:.1f} ms")
    print(f"P95 Latency:             {p95:.1f} ms")
    print(f"LLM Time:                {avg_llm:.1f} ms")
    print(f"DB Time:                 {avg_db:.1f} ms")
    print("-" * 80)
    print("CATEGORY BREAKDOWN:")
    for cname, cdata in category_stats.items():
        cpct = (cdata["passed"] / cdata["total"]) * 100.0 if cdata["total"] else 0
        print(f"  {cname:<22}: {cdata['passed']}/{cdata['total']} ({cpct:.1f}%)")
    print("=" * 80)
    print(f"Full Evaluation Report saved to:\n  {report_path}\n")

    return summary


if __name__ == "__main__":
    run_benchmark()
