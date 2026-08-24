"""
analytics.py
Hand-written, known-correct SQL analyses. These exist independently of the
AI/LLM layer for two reasons:
  1. You need to understand the business questions in SQL yourself before
     you can judge whether the AI's generated SQL is any good.
  2. They double as the "expected result" baseline for the evaluation set
     in evaluation/test_questions.py.
"""

from .database import execute_query

REVENUE_FILTER = "o.order_status = 'Completed'"


def total_revenue():
    q = f"""
        SELECT ROUND(SUM(oi.quantity * oi.unit_price), 2) AS total_revenue
        FROM order_items oi
        JOIN orders o ON oi.order_id = o.order_id
        WHERE {REVENUE_FILTER}
    """
    return execute_query(q)


def revenue_by_year():
    q = f"""
        SELECT strftime('%Y', o.order_date) AS year,
               ROUND(SUM(oi.quantity * oi.unit_price), 2) AS revenue
        FROM order_items oi
        JOIN orders o ON oi.order_id = o.order_id
        WHERE {REVENUE_FILTER}
        GROUP BY year
        ORDER BY year
    """
    return execute_query(q)


def revenue_by_month():
    q = f"""
        SELECT strftime('%Y-%m', o.order_date) AS month,
               ROUND(SUM(oi.quantity * oi.unit_price), 2) AS revenue
        FROM order_items oi
        JOIN orders o ON oi.order_id = o.order_id
        WHERE {REVENUE_FILTER}
        GROUP BY month
        ORDER BY month
    """
    return execute_query(q)


def revenue_by_category():
    q = f"""
        SELECT p.category AS category,
               ROUND(SUM(oi.quantity * oi.unit_price), 2) AS revenue
        FROM order_items oi
        JOIN products p ON oi.product_id = p.product_id
        JOIN orders o ON oi.order_id = o.order_id
        WHERE {REVENUE_FILTER}
        GROUP BY p.category
        ORDER BY revenue DESC
    """
    return execute_query(q)


def top_products(limit: int = 10):
    q = f"""
        SELECT p.product_name AS product_name,
               p.category AS category,
               ROUND(SUM(oi.quantity * oi.unit_price), 2) AS revenue
        FROM order_items oi
        JOIN products p ON oi.product_id = p.product_id
        JOIN orders o ON oi.order_id = o.order_id
        WHERE {REVENUE_FILTER}
        GROUP BY p.product_id
        ORDER BY revenue DESC
        LIMIT {int(limit)}
    """
    return execute_query(q)


def customer_summary(limit: int = 10):
    q = f"""
        SELECT c.customer_id AS customer_id,
               c.first_name || ' ' || c.last_name AS customer_name,
               c.customer_segment AS segment,
               COUNT(DISTINCT o.order_id) AS n_orders,
               ROUND(SUM(oi.quantity * oi.unit_price), 2) AS total_revenue,
               ROUND(SUM(oi.quantity * oi.unit_price) * 1.0
                     / COUNT(DISTINCT o.order_id), 2) AS avg_order_value,
               MAX(o.order_date) AS last_order_date
        FROM customers c
        JOIN orders o ON c.customer_id = o.customer_id
        JOIN order_items oi ON o.order_id = oi.order_id
        WHERE {REVENUE_FILTER}
        GROUP BY c.customer_id
        ORDER BY total_revenue DESC
        LIMIT {int(limit)}
    """
    return execute_query(q)


def profit_by_category():
    q = f"""
        SELECT p.category AS category,
               ROUND(SUM(oi.quantity * oi.unit_price), 2) AS revenue,
               ROUND(SUM(oi.quantity * p.purchase_price), 2) AS cogs,
               ROUND(SUM(oi.quantity * (oi.unit_price - p.purchase_price)), 2) AS gross_profit,
               ROUND(100.0 * SUM(oi.quantity * (oi.unit_price - p.purchase_price))
                     / SUM(oi.quantity * oi.unit_price), 2) AS gross_margin_pct
        FROM order_items oi
        JOIN products p ON oi.product_id = p.product_id
        JOIN orders o ON oi.order_id = o.order_id
        WHERE {REVENUE_FILTER}
        GROUP BY p.category
        ORDER BY gross_profit DESC
    """
    return execute_query(q)


def revenue_by_segment():
    q = f"""
        SELECT c.customer_segment AS segment,
               ROUND(SUM(oi.quantity * oi.unit_price), 2) AS revenue
        FROM order_items oi
        JOIN orders o ON oi.order_id = o.order_id
        JOIN customers c ON o.customer_id = c.customer_id
        WHERE {REVENUE_FILTER}
        GROUP BY c.customer_segment
        ORDER BY revenue DESC
    """
    return execute_query(q)


def return_rate_by_product(limit: int = 10):
    q = """
        SELECT p.product_name AS product_name,
               COUNT(DISTINCT o.order_id) AS n_orders,
               COUNT(DISTINCT CASE
                   WHEN o.order_status = 'Returned' THEN o.order_id
               END) AS n_returned,
               ROUND(100.0 * COUNT(DISTINCT CASE
                   WHEN o.order_status = 'Returned' THEN o.order_id
               END) / COUNT(DISTINCT o.order_id), 2) AS return_rate_pct
        FROM order_items oi
        JOIN orders o ON oi.order_id = o.order_id
        JOIN products p ON oi.product_id = p.product_id
        GROUP BY p.product_id
        HAVING n_orders >= 20
        ORDER BY return_rate_pct DESC
        LIMIT ?
    """
    return execute_query(q, (limit,))
