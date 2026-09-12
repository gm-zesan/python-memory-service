"""
Phase 3.x Benchmark Runner v2 - 3-Score Dual Engine Evaluator.
Evaluates:
- Score A: Frozen Regression Score (58 Cases)
- Score B: New Compositional Capability Score (20 Cases)
- Score C: Combined System Score (78 Cases)
Tracks provider metadata (OpenRouter vs DeepSeek Direct), failover triggers, and latencies.
Guarantees frozen Phase 3 control results are never overwritten.
"""

import os
import sys
import json
import time
from typing import Dict, Any, List, Optional, Tuple

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Phase 3 Baseline Imports
from app.analytics.planner import AnalyticsPlanner
from app.analytics.compiler import AnalyticsCompiler

# Phase 3.x Generic Semantic Engine Imports
from app.analytics.planner_v2 import SemanticPlannerV2
from app.analytics.compiler_v2 import AnalyticsCompilerV2
from app.analytics.models_v2 import SemanticQueryPlan
from app.analytics.validator_v2 import SemanticValidator
from app.analytics.executor import AnalyticsExecutor, SecurityViolationError


def results_match(actual: List[Dict[str, Any]], oracle: List[Dict[str, Any]]) -> bool:
    """
    Compares actual query result rows with oracle query result rows.
    Handles numeric tolerances, alias differences, and scalar extractions.
    """
    if actual == oracle:
        return True
    if len(actual) != len(oracle):
        if not (len(actual) == 1 and len(oracle) == 1):
            return False

    for r_act, r_ora in zip(actual, oracle):
        for k, v in r_ora.items():
            # Ignore surrogate database primary keys in oracle if not selected in actual
            if k in ("id", "salesperson_id", "customer_id", "product_id"):
                continue
            if k in r_act:
                act_v = r_act[k]
                if isinstance(v, (int, float)) and isinstance(act_v, (int, float)):
                    if abs(float(act_v) - float(v)) >= 0.05:
                        return False
                elif str(act_v).strip().lower() != str(v).strip().lower():
                    return False
            else:
                # Key alias might differ; search all values in actual row
                found = False
                for act_v in r_act.values():
                    if isinstance(v, (int, float)) and isinstance(act_v, (int, float)):
                        if abs(float(act_v) - float(v)) < 0.05:
                            found = True
                            break
                    elif str(act_v).strip().lower() == str(v).strip().lower():
                        found = True
                        break
                if not found:
                    return False
    return True


class BenchmarkRunnerV2:
    def __init__(self, workspace_id: int = 1):
        self.workspace_id = workspace_id
        self.executor = AnalyticsExecutor()

        # Engine v1 (Phase 3 Baseline)
        self.planner_v1 = AnalyticsPlanner()
        self.compiler_v1 = AnalyticsCompiler()

        # Engine v2 (Phase 3.x Generic Semantic Engine)
        self.planner_v2 = SemanticPlannerV2()
        self.compiler_v2 = AnalyticsCompilerV2()

        # Fixture paths
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.path_58 = os.path.join(base_dir, "tests", "fixtures", "analytics_benchmark_58.json")
        self.path_20 = os.path.join(base_dir, "tests", "fixtures", "analytics_benchmark_20_compositional.json")

    def _execute_oracle(self, oracle: Dict[str, Any]) -> List[Dict[str, Any]]:
        o_type = oracle.get("type")
        if o_type == "sql":
            sql = oracle["sql"]
            params = oracle.get("parameters", [self.workspace_id])
            rows, _ = self.executor.execute(sql, params)
            return rows
        elif o_type in ("security_rejection", "security_guard", "clarification", "clarification_guard"):
            return []
        return []

    def evaluate_case_v2(self, case: Dict[str, Any]) -> Dict[str, Any]:
        """Runs a single test case through Phase 3.x Generic Semantic Engine."""
        cid = case["id"]
        question = case["question"]
        oracle = case.get("oracle", {})

        plan, meta = self.planner_v2.plan(question)
        llm_ms = meta.get("latency_ms", 0.0)

        report = {
            "id": cid,
            "category": case.get("category", "general"),
            "question": question,
            "engine": "v2_semantic",
            "provider_used": meta.get("provider_used"),
            "model": meta.get("model"),
            "fallback_triggered": meta.get("fallback_triggered", False),
            "llm_latency_ms": round(llm_ms, 2),
            "db_latency_ms": 0.0,
            "total_latency_ms": 0.0,
            "passed": False,
            "failure_reason": None,
            "plan": plan.model_dump(),
        }

        o_type = oracle.get("type")
        expected_behavior = case.get("expected_behavior")

        # 1. Check Security Rejection cases
        if o_type in ("security_rejection", "security_guard") or expected_behavior == "REJECT":
            if plan.is_security_rejection:
                report["passed"] = True
            else:
                report["failure_reason"] = "Expected security rejection, but query was planned normally."
            report["total_latency_ms"] = round(llm_ms, 2)
            return report

        # 2. Check Clarification cases
        if o_type in ("clarification", "clarification_guard"):
            if plan.needs_clarification:
                report["passed"] = True
            else:
                report["failure_reason"] = "Expected clarification, but query was planned without clarification."
            report["total_latency_ms"] = round(llm_ms, 2)
            return report

        # Guard: If plan unexpectedly rejected or clarified
        if plan.is_security_rejection:
            report["failure_reason"] = f"Unexpected security rejection: {plan.rejection_reason}"
            report["total_latency_ms"] = round(llm_ms, 2)
            return report

        if plan.needs_clarification:
            report["failure_reason"] = f"Unexpected clarification triggered: {plan.clarification_message}"
            report["total_latency_ms"] = round(llm_ms, 2)
            return report

        # 3. Deterministic SQL Compilation
        try:
            sql, params = self.compiler_v2.compile(plan, self.workspace_id)
            report["compiled_sql"] = sql
            report["compiled_params"] = params
        except Exception as e_comp:
            report["failure_reason"] = f"Compilation Error: {str(e_comp)}"
            report["total_latency_ms"] = round(llm_ms, 2)
            return report

        # 4. Physical Execution & Oracle Verification
        try:
            actual_rows, db_ms = self.executor.execute(sql, params)
            report["db_latency_ms"] = round(db_ms, 2)
            report["total_latency_ms"] = round(llm_ms + db_ms, 2)
            report["actual_rows"] = actual_rows

            oracle_rows = self._execute_oracle(oracle)
            report["oracle_rows"] = oracle_rows

            if results_match(actual_rows, oracle_rows):
                report["passed"] = True
            else:
                report["failure_reason"] = f"Result mismatch. Actual: {actual_rows} vs Oracle: {oracle_rows}"

        except Exception as e_exec:
            report["failure_reason"] = f"Execution Error: {str(e_exec)}"
            report["total_latency_ms"] = round(llm_ms, 2)

        return report

    def evaluate_case_v1(self, case: Dict[str, Any]) -> Dict[str, Any]:
        """Runs a single test case through Phase 3 Baseline (Fixed Intent)."""
        cid = case["id"]
        question = case["question"]
        oracle = case.get("oracle", {})

        plan, llm_ms = self.planner_v1.plan(question)

        report = {
            "id": cid,
            "category": case.get("category", "general"),
            "question": question,
            "engine": "v1_baseline",
            "llm_latency_ms": round(llm_ms, 2),
            "db_latency_ms": 0.0,
            "total_latency_ms": 0.0,
            "passed": False,
            "failure_reason": None,
        }

        if oracle.get("type") == "security_rejection":
            report["passed"] = bool(plan.is_security_rejection)
            report["total_latency_ms"] = round(llm_ms, 2)
            return report

        if oracle.get("type") == "clarification":
            report["passed"] = bool(plan.needs_clarification)
            report["total_latency_ms"] = round(llm_ms, 2)
            return report

        if plan.is_security_rejection or plan.needs_clarification:
            report["failure_reason"] = "Premature rejection/clarification in v1"
            report["total_latency_ms"] = round(llm_ms, 2)
            return report

        try:
            sql, params = self.compiler_v1.compile(plan, self.workspace_id)
            if not sql:
                report["failure_reason"] = "v1 compiler returned empty SQL"
                return report

            actual_rows, db_ms = self.executor.execute(sql, params)
            report["db_latency_ms"] = round(db_ms, 2)
            report["total_latency_ms"] = round(llm_ms + db_ms, 2)

            oracle_rows = self._execute_oracle(oracle)
            if results_match(actual_rows, oracle_rows):
                report["passed"] = True
            else:
                report["failure_reason"] = f"Result mismatch: {actual_rows} vs {oracle_rows}"

        except Exception as err:
            report["failure_reason"] = f"Execution/Compile Error: {err}"

        return report

    def run_suite(self, suite_path: str, engine: str = "v2") -> Tuple[int, int, List[Dict[str, Any]]]:
        """Runs an entire test suite file with specified engine."""
        with open(suite_path, "r", encoding="utf-8") as f:
            suite_data = json.load(f)

        cases = suite_data.get("cases", [])
        passed = 0
        reports = []

        for idx, case in enumerate(cases, 1):
            cid = case["id"]
            if engine == "v2":
                rep = self.evaluate_case_v2(case)
            else:
                rep = self.evaluate_case_v1(case)

            if rep["passed"]:
                passed += 1
                status = "[PASS]"
            else:
                status = "[FAIL]"
                print(f"   x {cid} FAILED: {rep['failure_reason']}")

            reports.append(rep)
            time.sleep(0.1)  # gentle rate limit buffer

        return passed, len(cases), reports


def run_full_3score_benchmark(skip_v1_rerun: bool = True) -> Dict[str, Any]:
    """
    Executes the full 3-score evaluation:
    - Score A: 58 Frozen Regression Cases (evaluated on v2)
    - Score B: 20 Compositional Cases (evaluated on v1 vs v2)
    - Score C: Combined 78 Cases
    """
    runner = BenchmarkRunnerV2()

    print("\n" + "=" * 80)
    print("PHASE 3.x THREE-SCORE EVALUATION BENCHMARK")
    print("Score A: 58 Frozen Control Baseline Regression")
    print("Score B: 20 New Compositional Queries")
    print("Score C: 78 Combined Capability")
    print("=" * 80 + "\n")

    # 1. Run Score B (20 Compositional)
    total_20 = 20
    if not skip_v1_rerun:
        print("[1/3] Running Score B: 20 Compositional Cases on v1 Baseline...")
        pass_v1_20, total_20, reps_v1_20 = runner.run_suite(runner.path_20, engine="v1")
    else:
        print("[1/3] Using Frozen Control Baseline for Score B (v1): 9/20 (45.0%)...")
        pass_v1_20 = 9

    print("   -> Evaluating Phase 3.x Semantic Engine on Compositional Suite (20 cases)...")
    pass_v2_20, _, reps_v2_20 = runner.run_suite(runner.path_20, engine="v2")
    print(f"   -> Phase 3.x Semantic Engine on Compositional Suite: {pass_v2_20}/{total_20} ({pass_v2_20/total_20*100:.1f}%)")

    # 2. Run Score A (58 Frozen Baseline) on v2 Semantic Engine
    print("\n[2/3] Running Score A: 58 Frozen Baseline Cases on Phase 3.x Semantic Engine...")
    pass_v2_58, total_58, reps_v2_58 = runner.run_suite(runner.path_58, engine="v2")
    print(f"   -> Phase 3.x Semantic Engine on Frozen 58 Suite: {pass_v2_58}/{total_58} ({pass_v2_58/total_58*100:.1f}%)")

    # 3. Compute Score C (Combined 78 Cases)
    pass_combined = pass_v2_58 + pass_v2_20
    total_combined = total_58 + total_20
    combined_pct = (pass_combined / total_combined) * 100.0

    # Compile Summary
    summary = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "score_a_frozen_regression": {
            "passed": pass_v2_58,
            "total": total_58,
            "accuracy_pct": round((pass_v2_58 / total_58) * 100.0, 2),
            "historical_baseline_passed": 56,
            "historical_baseline_pct": 96.55,
        },
        "score_b_compositional": {
            "phase_3_baseline": {
                "passed": pass_v1_20,
                "total": total_20,
                "accuracy_pct": round((pass_v1_20 / total_20) * 100.0, 2),
            },
            "phase_3_x_semantic": {
                "passed": pass_v2_20,
                "total": total_20,
                "accuracy_pct": round((pass_v2_20 / total_20) * 100.0, 2),
            },
        },
        "score_c_combined": {
            "passed": pass_combined,
            "total": total_combined,
            "accuracy_pct": round(combined_pct, 2),
        },
    }

    # Save to JSON
    results_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "tests",
        "fixtures",
        "benchmark_run_v2_results.json",
    )
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    print("\n" + "=" * 80)
    print("FINAL BENCHMARK RESULTS")
    print(f"Score A (Frozen 58 Regression)  : {pass_v2_58}/{total_58} ({summary['score_a_frozen_regression']['accuracy_pct']}%) [Historical Baseline: 56/58 (96.55%)]")
    print(f"Score B (20 Compositional)      : {pass_v2_20}/{total_20} ({summary['score_b_compositional']['phase_3_x_semantic']['accuracy_pct']}%) [v1 Baseline: {pass_v1_20}/{total_20} (45.0%)]")
    print(f"Score C (Combined 78 Cases)     : {pass_combined}/{total_combined} ({round(combined_pct, 2)}%)")
    print(f"Saved benchmark summary to: {results_path}")
    print("=" * 80 + "\n")

    return summary


if __name__ == "__main__":
    run_full_3score_benchmark()
