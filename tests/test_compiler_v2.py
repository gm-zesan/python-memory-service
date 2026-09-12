"""
Unit Tests for Phase 3.x Deterministic SQL Compiler v2.
Verifies AST-to-SQL compilation, multi-tenant workspace_id parameter isolation,
pre-aggregated CTE due queries, and temporal filter generation.
"""

import unittest
from app.analytics.models_v2 import (
    DomainEnum,
    AggregationType,
    OperatorType,
    DerivedMetricType,
    DerivedMetricSpec,
    MeasureSpec,
    DimensionSpec,
    FilterSpec,
    TimeRangeSpec,
    OrderBySpec,
    SemanticQueryPlan,
)
from app.analytics.compiler_v2 import AnalyticsCompilerV2, CompilerError


class TestCompilerV2(unittest.TestCase):
    def setUp(self):
        self.compiler = AnalyticsCompilerV2()
        self.workspace_id = 42

    def test_global_sales_summary_compilation(self):
        plan = SemanticQueryPlan(
            domain=DomainEnum.SALES,
            measures=[MeasureSpec(name="sales_amount")],
            time_range=TimeRangeSpec(type="today"),
        )
        sql, params = self.compiler.compile(plan, self.workspace_id)
        self.assertIn("SELECT COALESCE(SUM(o.net_amount), 0) AS sales_amount", sql)
        self.assertIn("FROM analytics_orders o", sql)
        self.assertIn("o.workspace_id = ?", sql)
        self.assertIn("o.status = 'completed'", sql)
        self.assertIn("DATE(o.order_date) = CURRENT_DATE()", sql)
        self.assertEqual(params, [self.workspace_id])

    def test_salesperson_filtered_sales_compilation(self):
        plan = SemanticQueryPlan(
            domain=DomainEnum.SALES,
            measures=[MeasureSpec(name="sales_amount")],
            dimensions=[DimensionSpec(name="salesperson")],
            filters=[FilterSpec(field="salesperson", operator=OperatorType.EQUALS, value="Hasan")],
            time_range=TimeRangeSpec(type="last_7_days"),
        )
        sql, params = self.compiler.compile(plan, self.workspace_id)
        self.assertIn("JOIN analytics_salespersons s ON s.id = o.salesperson_id AND s.workspace_id = ?", sql)
        self.assertIn("s.name = ?", sql)
        self.assertIn(self.workspace_id, params)
        self.assertIn("Hasan", params)

    def test_grouped_sales_by_salesperson_compilation(self):
        plan = SemanticQueryPlan(
            domain=DomainEnum.SALES,
            measures=[MeasureSpec(name="sales_amount")],
            dimensions=[DimensionSpec(name="salesperson")],
            group_by=["salesperson"],
            order_by=[OrderBySpec(field="sales_amount", direction="desc")],
            limit=5,
        )
        sql, params = self.compiler.compile(plan, self.workspace_id)
        self.assertIn("GROUP BY s.name", sql)
        self.assertIn("ORDER BY sales_amount DESC", sql)
        self.assertIn("LIMIT 5", sql)

    def test_average_order_value_compilation(self):
        # As derived metric
        plan = SemanticQueryPlan(
            domain=DomainEnum.SALES,
            derived_metrics=[DerivedMetricSpec(type=DerivedMetricType.AVERAGE_ORDER_VALUE)],
        )
        sql, params = self.compiler.compile(plan, self.workspace_id)
        self.assertIn("ROUND(COALESCE(AVG(o.net_amount), 0), 2) AS average_order_value", sql)
        self.assertEqual(params, [self.workspace_id])

    def test_global_scalar_due_compilation(self):
        plan = SemanticQueryPlan(
            domain=DomainEnum.DUE,
            derived_metrics=[DerivedMetricSpec(type=DerivedMetricType.OUTSTANDING_DUE)],
        )
        sql, params = self.compiler.compile(plan, self.workspace_id)
        self.assertIn("analytics_orders WHERE workspace_id = ? AND status = 'completed'", sql)
        self.assertIn("analytics_payments WHERE workspace_id = ?", sql)
        self.assertIn("total_outstanding_due", sql)
        self.assertEqual(params, [self.workspace_id, self.workspace_id])

    def test_customer_due_list_with_threshold_compilation(self):
        plan = SemanticQueryPlan(
            domain=DomainEnum.DUE,
            derived_metrics=[DerivedMetricSpec(type=DerivedMetricType.OUTSTANDING_DUE)],
            filters=[FilterSpec(field="due_amount", operator=OperatorType.GREATER_THAN, value=5000)],
            group_by=["customer"],
        )
        sql, params = self.compiler.compile(plan, self.workspace_id)
        self.assertIn("FROM analytics_customers c WHERE c.workspace_id = ?", sql)
        self.assertIn("HAVING due_amount > ?", sql)
        self.assertEqual(params, [self.workspace_id, 5000.0])

    def test_specific_customer_due_lookup_compilation(self):
        plan = SemanticQueryPlan(
            domain=DomainEnum.DUE,
            derived_metrics=[DerivedMetricSpec(type=DerivedMetricType.OUTSTANDING_DUE)],
            filters=[FilterSpec(field="customer", operator=OperatorType.EQUALS, value="Rahim")],
        )
        sql, params = self.compiler.compile(plan, self.workspace_id)
        self.assertIn("WHERE c.workspace_id = ? AND c.name = ?", sql)
        self.assertEqual(params, [self.workspace_id, "Rahim"])

    def test_payments_cash_collection_compilation(self):
        plan = SemanticQueryPlan(
            domain=DomainEnum.PAYMENTS,
            measures=[MeasureSpec(name="collection_amount")],
            filters=[FilterSpec(field="payment_method", operator=OperatorType.EQUALS, value="bkash")],
            time_range=TimeRangeSpec(type="this_month"),
        )
        sql, params = self.compiler.compile(plan, self.workspace_id)
        self.assertIn("FROM analytics_payments p", sql)
        self.assertIn("p.workspace_id = ?", sql)
        self.assertIn("p.payment_method = ?", sql)
        self.assertIn("MONTH(p.collected_at) = MONTH(CURRENT_DATE())", sql)
        self.assertEqual(params, [self.workspace_id, "bkash"])

    def test_due_assignment_count_compilation(self):
        plan = SemanticQueryPlan(
            domain=DomainEnum.DUE_ASSIGNMENT,
            measures=[MeasureSpec(name="active_assignment_count")],
        )
        sql, params = self.compiler.compile(plan, self.workspace_id)
        self.assertIn("FROM analytics_due_assignments", sql)
        self.assertIn("workspace_id = ?", sql)
        self.assertIn("status IN ('assigned', 'in_progress')", sql)
        self.assertEqual(params, [self.workspace_id])

    def test_period_difference_sales_compilation(self):
        plan = SemanticQueryPlan(
            domain=DomainEnum.SALES,
            derived_metrics=[DerivedMetricSpec(type=DerivedMetricType.PERIOD_DIFFERENCE)],
            time_range=TimeRangeSpec(type="today"),
        )
        sql, params = self.compiler.compile(plan, self.workspace_id)
        self.assertIn("order_date = CURRENT_DATE()", sql)
        self.assertIn("order_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)", sql)
        self.assertEqual(params, [self.workspace_id, self.workspace_id])

    def test_workspace_isolation_invariant(self):
        # Ensure that no matter what filters or metrics are requested, workspace_id is strictly checked
        test_plans = [
            SemanticQueryPlan(domain=DomainEnum.SALES, measures=[MeasureSpec(name="sales_amount")]),
            SemanticQueryPlan(domain=DomainEnum.PAYMENTS, measures=[MeasureSpec(name="collection_amount")]),
            SemanticQueryPlan(domain=DomainEnum.DUE, derived_metrics=[DerivedMetricSpec(type=DerivedMetricType.OUTSTANDING_DUE)]),
            SemanticQueryPlan(domain=DomainEnum.DUE_ASSIGNMENT, measures=[MeasureSpec(name="active_assignment_count")]),
        ]
        for p in test_plans:
            sql, params = self.compiler.compile(p, 999)
            self.assertIn("workspace_id = ?", sql)
            self.assertIn(999, params)


if __name__ == "__main__":
    unittest.main()
