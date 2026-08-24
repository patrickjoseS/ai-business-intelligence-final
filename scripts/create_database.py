"""
create_database.py
Builds data/novashop.db (SQLite) from the CSVs in data/raw/ and defines
the relational schema with proper primary/foreign keys and indexes.

Uses only the Python standard library (sqlite3) for maximum portability.
"""

import csv
import os
import sqlite3

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
RAW_DIR = os.path.join(BASE_DIR, "data", "raw")
DB_PATH = os.path.join(BASE_DIR, "data", "novashop.db")

SCHEMA = """
DROP TABLE IF EXISTS order_items;
DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS products;
DROP TABLE IF EXISTS customers;

CREATE TABLE customers (
    customer_id INTEGER PRIMARY KEY,
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    email TEXT NOT NULL,
    city TEXT NOT NULL,
    country TEXT NOT NULL,
    registration_date TEXT NOT NULL,
    customer_segment TEXT NOT NULL CHECK (customer_segment IN ('Standard','Premium','Business'))
);

CREATE TABLE products (
    product_id INTEGER PRIMARY KEY,
    product_name TEXT NOT NULL,
    category TEXT NOT NULL,
    purchase_price REAL NOT NULL,
    selling_price REAL NOT NULL,
    launch_date TEXT NOT NULL
);

CREATE TABLE orders (
    order_id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL,
    order_date TEXT NOT NULL,
    payment_method TEXT NOT NULL,
    order_status TEXT NOT NULL CHECK (order_status IN ('Completed','Cancelled','Returned')),
    FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
);

CREATE TABLE order_items (
    order_item_id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL,
    unit_price REAL NOT NULL,
    FOREIGN KEY (order_id) REFERENCES orders(order_id),
    FOREIGN KEY (product_id) REFERENCES products(product_id)
);

CREATE INDEX idx_orders_customer ON orders(customer_id);
CREATE INDEX idx_orders_date ON orders(order_date);
CREATE INDEX idx_items_order ON order_items(order_id);
CREATE INDEX idx_items_product ON order_items(product_id);
"""


def load_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.executescript(SCHEMA)

    customers = load_csv(os.path.join(RAW_DIR, "customers.csv"))
    cur.executemany(
        "INSERT INTO customers VALUES (?,?,?,?,?,?,?,?)",
        [(c["customer_id"], c["first_name"], c["last_name"], c["email"],
          c["city"], c["country"], c["registration_date"], c["customer_segment"])
         for c in customers],
    )

    products = load_csv(os.path.join(RAW_DIR, "products.csv"))
    cur.executemany(
        "INSERT INTO products VALUES (?,?,?,?,?,?)",
        [(p["product_id"], p["product_name"], p["category"],
          p["purchase_price"], p["selling_price"], p["launch_date"])
         for p in products],
    )

    orders = load_csv(os.path.join(RAW_DIR, "orders.csv"))
    cur.executemany(
        "INSERT INTO orders VALUES (?,?,?,?,?)",
        [(o["order_id"], o["customer_id"], o["order_date"],
          o["payment_method"], o["order_status"]) for o in orders],
    )

    order_items = load_csv(os.path.join(RAW_DIR, "order_items.csv"))
    cur.executemany(
        "INSERT INTO order_items VALUES (?,?,?,?,?)",
        [(oi["order_item_id"], oi["order_id"], oi["product_id"],
          oi["quantity"], oi["unit_price"]) for oi in order_items],
    )

    conn.commit()

    # sanity checks
    for table in ("customers", "products", "orders", "order_items"):
        n = cur.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"{table}: {n} rows")

    conn.close()
    print(f"Database created at {os.path.abspath(DB_PATH)}")


if __name__ == "__main__":
    main()
