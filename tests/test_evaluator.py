import sqlite3
import unittest

from evaluator import Evaluator


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


if __name__ == "__main__":
    unittest.main()
