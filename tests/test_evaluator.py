import sqlite3
import unittest

from chatbi.evaluation.evaluator import Evaluator


class FakeDatabase:
    """Return predetermined results without connecting to a database."""

    def __init__(self, results):
        self.results = results

    def execute(self, sql):
        return self.results[sql]


class SQLiteDatabase:
    """Exercise result comparison against SQLite; this is not MySQL validation."""

    def __init__(self, connection):
        self.connection = connection

    def execute(self, sql):
        cursor = self.connection.execute(sql)
        return [column[0] for column in cursor.description], cursor.fetchall()


def evaluate_results(expected_sql, expected_result, generated_sql, generated_result, **case_options):
    database = FakeDatabase({expected_sql: expected_result, generated_sql: generated_result})
    case = {"question": "查询数据", "expected_sql": expected_sql, **case_options}
    return Evaluator(db_client=database).evaluate_one(case, lambda _: generated_sql)


class EvaluatorTests(unittest.TestCase):
    def test_result_order_matters_only_when_requested(self):
        expected_sql = "SELECT name FROM customers ORDER BY id ASC"
        generated_sql = "SELECT name FROM customers ORDER BY id DESC"
        for options, expected_match in [
            ({}, True),
            ({"order_sensitive": False}, True),
            ({"order_sensitive": True}, False),
        ]:
            with self.subTest(options=options):
                result = evaluate_results(
                    expected_sql,
                    (["name"], [("Alice",), ("Bob",)]),
                    generated_sql,
                    (["name"], [("Bob",), ("Alice",)]),
                    **options,
                )
                self.assertIsNone(result["error"])
                self.assertIs(result["execution_match"], expected_match)

    def test_order_sensitive_comparison_with_in_memory_sqlite(self):
        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        connection.execute("CREATE TABLE customers (id INTEGER, name TEXT)")
        connection.executemany(
            "INSERT INTO customers (id, name) VALUES (?, ?)",
            [(1, "Alice"), (2, "Bob")],
        )
        case = {
            "question": "按客户编号升序查询姓名",
            "expected_sql": "SELECT name FROM customers ORDER BY id ASC",
            "order_sensitive": True,
        }
        result = Evaluator(db_client=SQLiteDatabase(connection)).evaluate_one(
            case, lambda _: "SELECT name FROM customers ORDER BY id DESC"
        )
        self.assertIsNone(result["error"])
        self.assertEqual(result["detail"]["expected_row_count"], 2)
        self.assertEqual(result["detail"]["generated_row_count"], 2)
        self.assertFalse(result["execution_match"])
        self.assertEqual(result["detail"]["mismatch_reason"], "row_order_mismatch")

    def test_non_boolean_order_sensitive_is_rejected(self):
        expected_sql = "SELECT name FROM customers"
        generated_sql = "SELECT name FROM customers WHERE id > 0"
        for invalid in ["true", 1, None]:
            with self.subTest(order_sensitive=invalid):
                with self.assertRaises((TypeError, ValueError)):
                    evaluate_results(
                        expected_sql,
                        (["name"], [("Alice",)]),
                        generated_sql,
                        (["name"], [("Alice",)]),
                        order_sensitive=invalid,
                    )

    def test_empty_results_still_require_matching_column_names(self):
        result = evaluate_results(
            "SELECT customer_id FROM customers WHERE customer_id = 0",
            (["customer_id"], []),
            "SELECT customer_type FROM customers WHERE customer_id = 0",
            (["customer_type"], []),
        )
        self.assertFalse(result["execution_match"])

    def test_duplicate_column_names_do_not_discard_values(self):
        result = evaluate_results(
            "SELECT a.id, b.id FROM customers a CROSS JOIN customers b",
            (["id", "id"], [(1, 3)]),
            "SELECT a.id + 1 AS id, b.id FROM customers a CROSS JOIN customers b",
            (["id", "id"], [(2, 3)]),
        )
        self.assertFalse(result["execution_match"])

    def test_null_is_distinct_from_the_string_none(self):
        result = evaluate_results(
            "SELECT order_status FROM sales_orders",
            (["order_status"], [(None,)]),
            "SELECT COALESCE(order_status, 'None') AS order_status FROM sales_orders",
            (["order_status"], [("None",)]),
        )
        self.assertFalse(result["execution_match"])

    def test_equivalent_aggregate_values_may_use_different_aliases(self):
        result = evaluate_results(
            "SELECT COUNT(*) AS total FROM sales_orders",
            (["total"], [(7,)]),
            "SELECT COUNT(*) AS order_count FROM sales_orders",
            (["order_count"], [(7,)]),
        )
        self.assertTrue(result["execution_match"])

    def test_empty_evaluation_report_does_not_divide_by_zero(self):
        report = Evaluator(db_client=FakeDatabase({})).generate_report([])
        self.assertIn("总用例数：0", report)


    def test_mismatch_reasons_distinguish_columns_and_rows(self):
        expected_sql = "SELECT name FROM customers"
        generated_sql = "SELECT name FROM customers WHERE id > 0"
        cases = [
            ((["name"], [("Alice",)]), (["name", "id"], [("Alice", 1)]),
             "column_count_mismatch"),
            ((["name"], [("Alice",)]), (["name"], [("Alice",), ("Bob",)]),
             "row_count_mismatch"),
            ((["name"], []), (["id"], []), "column_name_mismatch"),
            ((["name"], [("Alice",)]), (["name"], [("Bob",)]), "row_values_mismatch"),
        ]
        for expected_result, generated_result, reason in cases:
            with self.subTest(reason=reason):
                result = evaluate_results(expected_sql, expected_result, generated_sql, generated_result)
                self.assertIsNone(result["error"])
                self.assertFalse(result["execution_match"])
                self.assertEqual(result["detail"]["mismatch_reason"], reason)

    def test_order_reason_only_when_values_match_without_order(self):
        expected_sql = "SELECT name FROM customers ORDER BY id ASC"
        generated_sql = "SELECT name FROM customers ORDER BY id DESC"
        expected = (["name"], [("Alice",), ("Bob",)])
        reversed_rows = (["name"], [("Bob",), ("Alice",)])
        changed_rows = (["name"], [("Bob",), ("Charlie",)])

        ordered = evaluate_results(expected_sql, expected, generated_sql, reversed_rows, order_sensitive=True)
        self.assertEqual(ordered["detail"]["mismatch_reason"], "row_order_mismatch")

        unordered = evaluate_results(expected_sql, expected, generated_sql, reversed_rows)
        self.assertTrue(unordered["execution_match"])
        self.assertIsNone(unordered["detail"].get("mismatch_reason"))

        changed = evaluate_results(expected_sql, expected, generated_sql, changed_rows, order_sensitive=True)
        self.assertEqual(changed["detail"]["mismatch_reason"], "row_values_mismatch")

    def test_execution_errors_are_not_diagnosed_as_result_mismatches(self):
        expected_sql = "SELECT name FROM customers"
        generated_sql = "SELECT name FROM customers WHERE id > 0"
        case = {"question": "查询客户", "expected_sql": expected_sql}
        result = Evaluator(db_client=FakeDatabase({})).evaluate_one(
            case, lambda _: (_ for _ in ()).throw(RuntimeError("generation failed"))
        )
        self.assertIsNotNone(result["error"])
        self.assertIsNone(result["detail"].get("mismatch_reason"))

        for db_results in ({}, {expected_sql: (["name"], [("Alice",)])}):
            with self.subTest(db_results=bool(db_results)):
                result = Evaluator(db_client=FakeDatabase(db_results)).evaluate_one(case, lambda _: generated_sql)
                self.assertIsNotNone(result["error"])
                self.assertIsNone(result["detail"].get("mismatch_reason"))

    def test_report_includes_reason_without_result_values(self):
        expected_sql = "SELECT name FROM customers ORDER BY id ASC"
        generated_sql = "SELECT name FROM customers ORDER BY id DESC"
        result = evaluate_results(
            expected_sql, (["name"], [("PRIVATE_A",), ("PRIVATE_B",)]),
            generated_sql, (["name"], [("PRIVATE_B",), ("PRIVATE_A",)]),
            order_sensitive=True,
        )
        report = Evaluator(db_client=FakeDatabase({})).generate_report([result])
        self.assertIn("row_order_mismatch", report)
        self.assertNotIn("PRIVATE_A", report)
        self.assertNotIn("PRIVATE_B", report)

    def test_report_accepts_results_from_before_diagnostics(self):
        result = {
            "id": "legacy", "category": "simple", "question": "查询客户",
            "generated_sql": "SELECT name FROM customers", "execution_match": False,
            "exact_match": False, "error": None,
            "detail": {"expected_row_count": 1, "generated_row_count": 1},
        }
        report = Evaluator(db_client=FakeDatabase({})).generate_report([result])
        self.assertIn("legacy", report)


if __name__ == "__main__":
    unittest.main()
