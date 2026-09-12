"""
Unit Tests for Phase 3.x Semantic Contracts, Models v2, and Registries.
Verifies AST serialization, Relationship fanout classification,
typed filter validation, and Capability Matrix enforcement.
Written using standard library unittest for zero-dependency test execution.
"""

import unittest
from app.analytics.models_v2 import (
    DomainEnum,
    AggregationType,
    OperatorType,
    CardinalityType,
    FanoutRisk,
    MeasureSpec,
    DimensionSpec,
    FilterSpec,
    TimeRangeSpec,
    OrderBySpec,
    DerivedMetricType,
    DerivedMetricSpec,
    SemanticQueryPlan,
)
from app.analytics.registries import (
    MEASURE_REGISTRY,
    DIMENSION_REGISTRY,
    RELATIONSHIP_REGISTRY,
    DERIVED_METRIC_REGISTRY,
    CAPABILITY_MATRIX,
    get_measure,
    get_dimension,
    get_relationship,
    get_derived_metric,
    get_fanout_risk,
    validate_filter_value_type,
    validate_plan_semantics,
)


class TestModelsV2(unittest.TestCase):
    """Test AST models and specifications."""

    def test_semantic_query_plan_serialization(self):
        plan = SemanticQueryPlan(
            domain=DomainEnum.SALES,
            measures=[
                MeasureSpec(name="sales_amount", aggregation=AggregationType.SUM),
                MeasureSpec(name="order_count", aggregation=AggregationType.COUNT),
            ],
            dimensions=[DimensionSpec(name="salesperson")],
            filters=[
                FilterSpec(field="salesperson", operator=OperatorType.EQUALS, value="Hasan"),
                FilterSpec(field="sales_amount", operator=OperatorType.GREATER_THAN, value=1000),
            ],
            group_by=["salesperson"],
            time_range=TimeRangeSpec(type="last_7_days"),
            order_by=[OrderBySpec(field="sales_amount", direction="desc")],
            limit=10,
            derived_metrics=[
                DerivedMetricSpec(type=DerivedMetricType.AVERAGE_ORDER_VALUE)
            ],
        )

        data = plan.model_dump()
        self.assertEqual(data["domain"], "sales")
        self.assertEqual(len(data["measures"]), 2)
        self.assertEqual(data["filters"][0]["value"], "Hasan")
        self.assertEqual(data["filters"][1]["value"], 1000)
        self.assertEqual(data["derived_metrics"][0]["type"], "average_order_value")

        # Round trip deserialization
        recreated = SemanticQueryPlan.model_validate(data)
        self.assertEqual(recreated.domain, DomainEnum.SALES)
        self.assertEqual(len(recreated.measures), 2)

    def test_filter_spec_operator_validation(self):
        f1 = FilterSpec(field="salesperson", operator=OperatorType.EQUALS, value="Hasan")
        self.assertEqual(f1.operator, OperatorType.EQUALS)

        f2 = FilterSpec(field="sales_amount", operator=">=", value=500)
        self.assertEqual(f2.operator, OperatorType.GREATER_EQUAL)

        f3 = FilterSpec(field="sales_amount", operator=OperatorType.BETWEEN, value=[100, 500])
        self.assertEqual(f3.value, [100, 500])

        f4 = FilterSpec(field="salesperson", operator=OperatorType.IN, value=["Hasan", "Rahim"])
        self.assertEqual(len(f4.value), 2)

        f5 = FilterSpec(field="salesperson", operator=OperatorType.IS_NULL)
        self.assertIsNone(f5.value)

    def test_filter_spec_invalid_shapes(self):
        with self.assertRaises(ValueError):
            FilterSpec(field="sales_amount", operator=OperatorType.GREATER_THAN, value=None)

        with self.assertRaises(ValueError):
            FilterSpec(field="sales_amount", operator=OperatorType.BETWEEN, value=[100])

        with self.assertRaises(ValueError):
            FilterSpec(field="salesperson", operator=OperatorType.IN, value=[])

    def test_time_range_spec_validation(self):
        t1 = TimeRangeSpec(type="last_7_days")
        self.assertEqual(t1.type, "last_7_days")

        t2 = TimeRangeSpec(type="last_n_days", n_days=30)
        self.assertEqual(t2.n_days, 30)

        with self.assertRaises(ValueError):
            TimeRangeSpec(type="last_n_days", n_days=None)

        t3 = TimeRangeSpec(type="custom_range", start_date="2026-09-01", end_date="2026-09-12")
        self.assertEqual(t3.start_date, "2026-09-01")

        with self.assertRaises(ValueError):
            TimeRangeSpec(type="custom_range", start_date="2026-09-01")


class TestRegistries(unittest.TestCase):
    """Test registry contents, lookups, and metadata."""

    def test_measure_registry_lookups(self):
        sales = get_measure("sales_amount")
        self.assertIsNotNone(sales)
        self.assertEqual(sales.source_table, "analytics_orders")
        self.assertEqual(sales.source_column, "net_amount")
        self.assertEqual(sales.data_type, "currency")
        self.assertEqual(sales.default_scope_filter, "status = 'completed'")

        collection = get_measure("collection_amount")
        self.assertIsNotNone(collection)
        self.assertEqual(collection.source_table, "analytics_payments")
        self.assertEqual(collection.domain, DomainEnum.PAYMENTS)

        self.assertIsNone(get_measure("unknown_measure"))

    def test_dimension_registry_lookups(self):
        salesperson = get_dimension("salesperson")
        self.assertIsNotNone(salesperson)
        self.assertEqual(salesperson.source_table, "analytics_salespersons")
        self.assertEqual(salesperson.label_column, "name")

        category = get_dimension("category")
        self.assertIsNotNone(category)
        self.assertEqual(category.domain, DomainEnum.PRODUCT)

    def test_relationship_registry_cardinality_and_fanout(self):
        # Orders -> Customers: Many to One, Low risk
        rel_cust = get_relationship("orders", "customers")
        self.assertIsNotNone(rel_cust)
        self.assertEqual(rel_cust.cardinality, CardinalityType.MANY_TO_ONE)
        self.assertEqual(rel_cust.fanout_risk, FanoutRisk.LOW)
        self.assertFalse(rel_cust.requires_pre_aggregation)

        # Orders -> Order Items: One to Many, High risk
        rel_items = get_relationship("orders", "order_items")
        self.assertIsNotNone(rel_items)
        self.assertEqual(rel_items.cardinality, CardinalityType.ONE_TO_MANY)
        self.assertEqual(rel_items.fanout_risk, FanoutRisk.HIGH)
        self.assertTrue(rel_items.requires_pre_aggregation)

        # Orders <-> Payments: Many to Many cross-grain, Extreme Cartesian risk
        rel_pay = get_relationship("orders", "payments")
        self.assertIsNotNone(rel_pay)
        self.assertEqual(rel_pay.cardinality, CardinalityType.MANY_TO_MANY)
        self.assertEqual(rel_pay.fanout_risk, FanoutRisk.EXTREME_CARTESIAN)
        self.assertTrue(rel_pay.requires_pre_aggregation)

    def test_derived_metric_average_order_value(self):
        aov = get_derived_metric(DerivedMetricType.AVERAGE_ORDER_VALUE)
        self.assertIsNotNone(aov)
        self.assertEqual(aov.canonical_formula, "SUM(sales_amount) / COUNT(orders)")
        self.assertEqual(aov.base_measures, ["sales_amount", "order_count"])
        self.assertEqual(aov.optimized_single_table_expr, "AVG(net_amount)")

    def test_derived_metric_outstanding_due(self):
        due = get_derived_metric(DerivedMetricType.OUTSTANDING_DUE)
        self.assertIsNotNone(due)
        self.assertIn("orders.net_amount", due.canonical_formula)
        self.assertIn("payments.amount", due.canonical_formula)
        self.assertEqual(due.grain_strategy, "pre_aggregated_cte_merge")


class TestTypedFilterValidation(unittest.TestCase):
    """Test typed filter value semantic type guards."""

    def test_typed_filter_numeric_field_guards(self):
        # Valid numeric comparisons
        valid, err = validate_filter_value_type("sales_amount", OperatorType.GREATER_THAN, 5000)
        self.assertTrue(valid)
        self.assertIsNone(err)

        valid, err = validate_filter_value_type("sales_amount", OperatorType.GREATER_THAN, "5000.50")
        self.assertTrue(valid)
        self.assertIsNone(err)

        # CRITICAL USER TEST CASE: String passed to numeric measure
        valid, err = validate_filter_value_type("sales_amount", OperatorType.GREATER_THAN, "Hasan")
        self.assertFalse(valid)
        self.assertIn("expects a numeric value", err)

        # Boolean passed to numeric
        valid, err = validate_filter_value_type("order_count", OperatorType.EQUALS, True)
        self.assertFalse(valid)

        # Numeric BETWEEN
        valid, err = validate_filter_value_type("sales_amount", OperatorType.BETWEEN, [1000, 5000])
        self.assertTrue(valid)

        valid, err = validate_filter_value_type("sales_amount", OperatorType.BETWEEN, [1000, "invalid"])
        self.assertFalse(valid)

    def test_typed_filter_string_field_guards(self):
        valid, err = validate_filter_value_type("salesperson", OperatorType.EQUALS, "Hasan")
        self.assertTrue(valid)
        self.assertIsNone(err)

        valid, err = validate_filter_value_type("salesperson", OperatorType.IN, ["Hasan", "Rahim"])
        self.assertTrue(valid)
        self.assertIsNone(err)

        # BETWEEN on string field rejected
        valid, err = validate_filter_value_type("salesperson", OperatorType.BETWEEN, ["A", "B"])
        self.assertFalse(valid)

    def test_typed_filter_date_field_guards(self):
        valid, err = validate_filter_value_type("order_date", OperatorType.EQUALS, "2026-09-12")
        self.assertTrue(valid)

        valid, err = validate_filter_value_type("order_date", OperatorType.BETWEEN, ["2026-09-01", "2026-09-12"])
        self.assertTrue(valid)

        valid, err = validate_filter_value_type("order_date", OperatorType.EQUALS, 12345)
        self.assertFalse(valid)


class TestCapabilityMatrixAndPlanValidation(unittest.TestCase):
    """Test full semantic query plan validation."""

    def test_valid_sales_plan(self):
        plan = SemanticQueryPlan(
            domain=DomainEnum.SALES,
            measures=[MeasureSpec(name="sales_amount", aggregation=AggregationType.SUM)],
            dimensions=[DimensionSpec(name="salesperson")],
            filters=[FilterSpec(field="salesperson", operator=OperatorType.EQUALS, value="Hasan")],
            group_by=["salesperson"],
        )
        errors = validate_plan_semantics(plan)
        self.assertEqual(len(errors), 0)

    def test_cross_domain_measure_rejection(self):
        plan = SemanticQueryPlan(
            domain=DomainEnum.SALES,
            measures=[MeasureSpec(name="collection_amount")],
        )
        errors = validate_plan_semantics(plan)
        self.assertGreater(len(errors), 0)
        self.assertIn("collection_amount", errors[0])

    def test_cross_domain_dimension_rejection(self):
        plan = SemanticQueryPlan(
            domain=DomainEnum.PAYMENTS,
            measures=[MeasureSpec(name="collection_amount")],
            group_by=["category"],
        )
        errors = validate_plan_semantics(plan)
        self.assertTrue(any("category" in err for err in errors))

    def test_invalid_filter_type_in_plan(self):
        # User scenario: field="sales_amount", operator=">", value="Hasan"
        plan = SemanticQueryPlan(
            domain=DomainEnum.SALES,
            measures=[MeasureSpec(name="sales_amount")],
            filters=[FilterSpec(field="sales_amount", operator=OperatorType.GREATER_THAN, value="Hasan")],
        )
        errors = validate_plan_semantics(plan)
        self.assertGreater(len(errors), 0)
        self.assertIn("expects a numeric value", errors[0])


from app.analytics.validator_v2 import SemanticValidator, GrainAnalysisResult, ValidationResult


class TestSemanticValidator(unittest.TestCase):
    """Test grain analysis and SemanticValidator workflow."""

    def test_global_scalar_sales_plan(self):
        plan = SemanticQueryPlan(
            domain=DomainEnum.SALES,
            measures=[MeasureSpec(name="sales_amount")],
        )
        res = SemanticValidator.validate(plan)
        self.assertTrue(res.is_valid)
        self.assertIsNotNone(res.grain_analysis)
        self.assertEqual(res.grain_analysis.primary_grain, "global_scalar")
        self.assertFalse(res.grain_analysis.requires_pre_aggregation)
        self.assertEqual(res.grain_analysis.fanout_risk, FanoutRisk.LOW)

    def test_due_domain_grain_analysis_triggers_pre_aggregation(self):
        plan = SemanticQueryPlan(
            domain=DomainEnum.DUE,
            derived_metrics=[DerivedMetricSpec(type=DerivedMetricType.OUTSTANDING_DUE)],
            group_by=["customer"],
        )
        res = SemanticValidator.validate(plan)
        self.assertTrue(res.is_valid)
        self.assertIsNotNone(res.grain_analysis)
        self.assertEqual(res.grain_analysis.primary_grain, "customer")
        self.assertTrue(res.grain_analysis.requires_pre_aggregation)
        self.assertEqual(res.grain_analysis.pre_aggregation_entities, ["orders", "payments"])
        self.assertEqual(res.grain_analysis.fanout_risk, FanoutRisk.EXTREME_CARTESIAN)

    def test_empty_measures_and_metrics_rejected(self):
        plan = SemanticQueryPlan(
            domain=DomainEnum.SALES,
            measures=[],
            derived_metrics=[],
        )
        res = SemanticValidator.validate(plan)
        self.assertFalse(res.is_valid)
        self.assertIn("at least one measure", res.errors[0])

    def test_clarification_flag_passes_through(self):
        plan = SemanticQueryPlan(
            domain=DomainEnum.SALES,
            needs_clarification=True,
            clarification_message="Did you mean today or this month?",
        )
        res = SemanticValidator.validate(plan)
        self.assertTrue(res.is_valid)
        self.assertTrue(res.sanitized_plan.needs_clarification)

    def test_security_rejection_blocks_execution(self):
        plan = SemanticQueryPlan(
            domain=DomainEnum.SALES,
            is_security_rejection=True,
            rejection_reason="SQL injection pattern detected.",
        )
        res = SemanticValidator.validate(plan)
        self.assertFalse(res.is_valid)
        self.assertIn("SQL injection pattern", res.errors[0])


if __name__ == "__main__":
    unittest.main()
