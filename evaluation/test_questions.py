"""
evaluation/test_questions.py
Text-to-SQL evaluation set for the NovaShop BI assistant.

Each question has a hand-written reference query. The generated query is
executed against the same database and the returned business result is
compared, including categorical/text values as well as numeric values.

Usage:
    python evaluation/test_questions.py

Requires GEMINI_API_KEY for the LLM portion. Local SQL/safety checks can
still be run without an API key by importing the helper functions.
"""

from __future__ import annotations

import math
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd
from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True)

from src import ai, database


REVENUE_FILTER = "o.order_status = 'Completed'"


TEST_CASES = [
    {
        "question": "What was our total revenue in 2025?",
        "expected_sql": f"""
            SELECT ROUND(SUM(oi.quantity*oi.unit_price),2) AS revenue
            FROM order_items oi JOIN orders o ON oi.order_id=o.order_id
            WHERE {REVENUE_FILTER} AND strftime('%Y', o.order_date)='2025'
        """,
    },
    {
        "question": "Which product category generated the highest revenue?",
        "expected_sql": f"""
            SELECT p.category, SUM(oi.quantity*oi.unit_price) AS revenue
            FROM order_items oi JOIN products p ON oi.product_id=p.product_id
            JOIN orders o ON oi.order_id=o.order_id
            WHERE {REVENUE_FILTER}
            GROUP BY p.category ORDER BY revenue DESC LIMIT 1
        """,
    },
    {
        "question": "Which category has the highest gross margin?",
        "expected_sql": f"""
            SELECT p.category,
                   100.0*SUM(oi.quantity*(oi.unit_price-p.purchase_price))
                   /SUM(oi.quantity*oi.unit_price) AS gross_margin_pct
            FROM order_items oi JOIN products p ON oi.product_id=p.product_id
            JOIN orders o ON oi.order_id=o.order_id
            WHERE {REVENUE_FILTER}
            GROUP BY p.category ORDER BY gross_margin_pct DESC LIMIT 1
        """,
    },
    {
        "question": "How many orders do we have in total?",
        "expected_sql": "SELECT COUNT(*) AS n_orders FROM orders",
    },
    {
        "question": "How many customers are registered?",
        "expected_sql": "SELECT COUNT(*) AS n_customers FROM customers",
    },
    {
        "question": "What is the average order value?",
        "expected_sql": f"""
            SELECT SUM(oi.quantity*oi.unit_price)*1.0/COUNT(DISTINCT o.order_id) AS aov
            FROM order_items oi JOIN orders o ON oi.order_id=o.order_id
            WHERE {REVENUE_FILTER}
        """,
    },
    {
        "question": "Which customer segment has the highest average order value?",
        "expected_sql": f"""
            SELECT c.customer_segment,
                   SUM(oi.quantity*oi.unit_price)*1.0/COUNT(DISTINCT o.order_id) AS aov
            FROM order_items oi JOIN orders o ON oi.order_id=o.order_id
            JOIN customers c ON o.customer_id=c.customer_id
            WHERE {REVENUE_FILTER}
            GROUP BY c.customer_segment ORDER BY aov DESC LIMIT 1
        """,
    },
    {
        "question": "How many products do we sell?",
        "expected_sql": "SELECT COUNT(*) AS n_products FROM products",
    },
    {
        "question": "What percentage of orders were cancelled?",
        "expected_sql": """
            SELECT 100.0*SUM(CASE WHEN order_status='Cancelled' THEN 1 ELSE 0 END)
                   /COUNT(*) AS cancelled_pct
            FROM orders
        """,
    },
    {
        "question": "Which payment method is used most often?",
        "expected_sql": """
            SELECT payment_method, COUNT(*) AS n
            FROM orders GROUP BY payment_method ORDER BY n DESC LIMIT 1
        """,
    },
    {
        "question": "How did revenue change from 2024 to 2025?",
        "expected_sql": f"""
            SELECT strftime('%Y', o.order_date) AS year,
                   SUM(oi.quantity*oi.unit_price) AS revenue
            FROM order_items oi JOIN orders o ON oi.order_id=o.order_id
            WHERE {REVENUE_FILTER}
              AND strftime('%Y', o.order_date) IN ('2024','2025')
            GROUP BY year ORDER BY year
        """,
        "order_sensitive": True,
    },
    {
        "question": "Which cities generate the most revenue?",
        "expected_sql": f"""
            SELECT c.city, SUM(oi.quantity*oi.unit_price) AS revenue
            FROM order_items oi JOIN orders o ON oi.order_id=o.order_id
            JOIN customers c ON o.customer_id=c.customer_id
            WHERE {REVENUE_FILTER}
            GROUP BY c.city ORDER BY revenue DESC LIMIT 10
        """,
        "order_sensitive": True,
    },
    {
        "question": "What is our total gross profit?",
        "expected_sql": f"""
            SELECT SUM(oi.quantity*(oi.unit_price-p.purchase_price)) AS gross_profit
            FROM order_items oi JOIN products p ON oi.product_id=p.product_id
            JOIN orders o ON oi.order_id=o.order_id
            WHERE {REVENUE_FILTER}
        """,
    },
    {
        "question": "How many Premium customers do we have?",
        "expected_sql": """
            SELECT COUNT(*) AS n
            FROM customers
            WHERE customer_segment='Premium'
        """,
    },
    {
        "question": "What was the revenue in December across all years?",
        "expected_sql": f"""
            SELECT SUM(oi.quantity*oi.unit_price) AS revenue
            FROM order_items oi JOIN orders o ON oi.order_id=o.order_id
            WHERE {REVENUE_FILTER}
              AND strftime('%m', o.order_date)='12'
        """,
    },
    {
        "question": "Which 5 products have the highest profit?",
        "expected_sql": f"""
            SELECT p.product_name,
                   SUM(oi.quantity*(oi.unit_price-p.purchase_price)) AS profit
            FROM order_items oi JOIN products p ON oi.product_id=p.product_id
            JOIN orders o ON oi.order_id=o.order_id
            WHERE {REVENUE_FILTER}
            GROUP BY p.product_id
            ORDER BY profit DESC
            LIMIT 5
        """,
        "order_sensitive": True,
    },
    {
        "question": "What is the return rate overall?",
        "expected_sql": """
            SELECT 100.0*SUM(CASE WHEN order_status='Returned' THEN 1 ELSE 0 END)
                   /COUNT(*) AS return_rate_pct
            FROM orders
        """,
    },
    {
        "question": "How many orders did Business customers place?",
        "expected_sql": """
            SELECT COUNT(*) AS n
            FROM orders o
            JOIN customers c ON o.customer_id=c.customer_id
            WHERE c.customer_segment='Business'
        """,
    },
    {
        "question": "What is the earliest and latest order date in the database?",
        "expected_sql": """
            SELECT MIN(order_date) AS first_order,
                   MAX(order_date) AS last_order
            FROM orders
        """,
    },
    {
        "question": "List our employees and their salaries.",
        "expected_sql": None,
    },
]


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _norm_text(value) -> str:
    return " ".join(str(value).strip().casefold().split())


def _scalar_match(expected, actual, tol: float) -> bool:
    if pd.isna(expected) and pd.isna(actual):
        return True

    if pd.isna(expected) or pd.isna(actual):
        return False

    if _is_number(expected) and _is_number(actual):
        e = float(expected)
        a = float(actual)
        return math.isclose(
            a,
            e,
            rel_tol=tol,
            abs_tol=tol,
        )

    return _norm_text(expected) == _norm_text(actual)


def _row_match(
    expected_row: list,
    actual_row: list,
    tol: float,
) -> bool:
    return (
        len(expected_row) == len(actual_row)
        and all(
            _scalar_match(e, a, tol)
            for e, a in zip(expected_row, actual_row)
        )
    )


def _row_signature(row: list) -> tuple:
    out = []

    for value in row:
        if pd.isna(value):
            out.append(("null", ""))

        elif _is_number(value):
            out.append(("num", round(float(value), 8)))

        else:
            out.append(("text", _norm_text(value)))

    return tuple(out)


def compare_results(
    expected: pd.DataFrame | None,
    actual: pd.DataFrame | None,
    *,
    tol: float = 0.02,
    order_sensitive: bool = False,
) -> str:
    """
    Return Correct, Partially Correct, or Incorrect.

    Correct:
      Same result shape and all values match.

    Partially Correct:
      At least one expected result row matches, but the full result
      does not match.

    Incorrect:
      No meaningful result match exists.
    """

    if expected is None:
        return "Correct" if actual is None else "Incorrect"

    if actual is None or actual.empty:
        return "Incorrect"

    if expected.empty:
        return "Correct" if actual.empty else "Incorrect"

    exp_rows = expected.astype(object).values.tolist()
    act_rows = actual.astype(object).values.tolist()

    same_shape = expected.shape == actual.shape

    if not order_sensitive:
        exp_rows = sorted(
            exp_rows,
            key=_row_signature,
        )

        act_rows = sorted(
            act_rows,
            key=_row_signature,
        )

    if (
        same_shape
        and all(
            _row_match(e, a, tol)
            for e, a in zip(exp_rows, act_rows)
        )
    ):
        return "Correct"

    remaining = list(act_rows)
    matched = 0

    for exp_row in exp_rows:
        for idx, act_row in enumerate(remaining):
            if _row_match(exp_row, act_row, tol):
                matched += 1
                remaining.pop(idx)
                break

    if matched > 0:
        return "Partially Correct"

    return "Incorrect"


def _classify_api_error(exc: Exception) -> bool:
    """
    Return True when an exception represents an external API/quota problem
    rather than a Text-to-SQL correctness failure.
    """

    text = str(exc).upper()

    api_error_markers = [
        "RESOURCE_EXHAUSTED",
        "429",
        "QUOTA",
        "RATE LIMIT",
        "RATE_LIMIT",
        "TOO MANY REQUESTS",
        "503",
        "SERVICE UNAVAILABLE",
        "UNAVAILABLE",
        "TIMEOUT",
        "TIMED OUT",
        "CONNECTION ERROR",
        "CONNECTIONERROR",
    ]

    return any(
        marker in text
        for marker in api_error_markers
    )


def run_safety_checks() -> None:
    """
    Local SQL-validator regression checks.

    These checks do not require Gemini API access.
    """

    dangerous = [
        "DROP TABLE customers",
        "DELETE FROM customers",
        "UPDATE customers SET city='X'",
        (
            "INSERT INTO customers VALUES "
            "(1,'a','b','c','d','e','2025-01-01','Standard')"
        ),
        "ALTER TABLE customers ADD COLUMN x TEXT",
        "CREATE TABLE employees(id INTEGER)",
        "ATTACH DATABASE 'x.db' AS x",
        "PRAGMA table_info(customers)",
        "VACUUM",
        "REPLACE INTO customers(customer_id) VALUES (1)",
        "TRUNCATE TABLE customers",
    ]

    for sql in dangerous:
        try:
            ai.validate_sql(sql)

        except ai.SQLValidationError:
            continue

        raise AssertionError(
            f"Unsafe SQL was not rejected: {sql}"
        )

    try:
        ai.validate_sql(
            "SELECT * FROM employees"
        )

    except ai.SQLValidationError:
        pass

    else:
        raise AssertionError(
            "Unknown table 'employees' was not rejected"
        )

    safe = ai.validate_sql(
        "SELECT customer_id FROM customers",
        enforce_row_limit=False,
    )

    assert safe.upper().startswith("SELECT")


def run_evaluation():
    if not os.environ.get("GEMINI_API_KEY"):
        raise RuntimeError(
            "GEMINI_API_KEY is not set. "
            "The local SQL/safety checks can run, "
            "but an LLM accuracy score cannot be measured "
            "without API access."
        )

    results = []

    for case in TEST_CASES:
        question = case["question"]

        expected_df = None

        if case["expected_sql"] is not None:
            expected_df = database.execute_query(
                case["expected_sql"]
            )

        sql = None
        actual_df = None
        error_type = None
        error_message = None

        try:
            gen = ai.generate_sql(question)

            sql = gen["sql"]

            if (
                sql.strip().upper()
                == "NO_QUERY_POSSIBLE"
            ):
                actual_df = None

            else:
                actual_df = database.execute_query(
                    sql
                )

        except ai.SQLValidationError as exc:
            error_type = "validation"
            error_message = str(exc)

        except Exception as exc:
            error_message = str(exc)

            if _classify_api_error(exc):
                error_type = "api"
            else:
                error_type = "execution"

        if error_type == "api":
            verdict = "API Error"

        elif error_type is not None:
            verdict = "Incorrect"

        else:
            verdict = compare_results(
                expected_df,
                actual_df,
                order_sensitive=case.get(
                    "order_sensitive",
                    False,
                ),
            )

        results.append(
            {
                "question": question,
                "sql": sql,
                "verdict": verdict,
                "error_type": error_type,
                "error_message": error_message,
            }
        )

        print(
            f"[{verdict:17s}] {question}"
        )

        if verdict == "API Error":
            print(
                "External Gemini API/quota error. "
                "This case is not counted as a Text-to-SQL failure."
            )
            print("-" * 80)

        elif verdict != "Correct":
            print("Generated SQL:")
            print(
                sql
                if sql
                else "(no SQL generated)"
            )

            if error_message:
                print(
                    f"Error: {error_message}"
                )

            print("-" * 80)

    counts = Counter(
        result["verdict"]
        for result in results
    )

    total = len(results)

    correct = counts["Correct"]
    partial = counts["Partially Correct"]
    incorrect = counts["Incorrect"]
    api_errors = counts["API Error"]

    completed = (
        correct
        + partial
        + incorrect
    )

    print("\nEvaluation summary")
    print(f"Total Questions: {total}")
    print(f"Completed LLM Cases: {completed}")
    print(f"Correct: {correct}")
    print(f"Partially Correct: {partial}")
    print(f"Incorrect: {incorrect}")
    print(f"API Errors: {api_errors}")

    if api_errors == 0:
        accuracy = (
            100 * correct / total
            if total
            else 0
        )

        print(
            f"Exact Accuracy: {accuracy:.1f}%"
        )

    else:
        print(
            "Exact Accuracy: not reported "
            "because the evaluation was incomplete "
            "due to external API/quota errors."
        )

        if completed > 0:
            provisional_accuracy = (
                100 * correct / completed
            )

            print(
                "Provisional accuracy on completed cases: "
                f"{provisional_accuracy:.1f}% "
                f"({correct}/{completed})"
            )

    return results


if __name__ == "__main__":
    run_safety_checks()

    print(
        "Local safety checks: PASS"
    )

    run_evaluation()