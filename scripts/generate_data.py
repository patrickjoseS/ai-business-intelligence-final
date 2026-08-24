"""
generate_data.py
Generates synthetic but realistic data for the fictional NovaShop GmbH
electronics retailer: customers, products, orders, order_items.

Deliberately built with only the Python standard library + numpy so the
whole project runs with zero network access / external services required
for data generation (Faker is intentionally avoided here - see README
"Design Decisions"). Swap in Faker easily if you prefer richer names.

Business trends baked into the data on purpose (see README):
  1. Revenue grows year over year: 2023 < 2024 < 2025
  2. Premium customers order more frequently
  3. Smartphones have high revenue
  4. Accessories have high margins
  5. Nov/Dec seasonal spike
  6. A handful of products have elevated return rates
"""

import csv
import os
import random
from datetime import date, timedelta

import numpy as np

random.seed(42)
np.random.seed(42)

OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "raw")
os.makedirs(OUT_DIR, exist_ok=True)

N_CUSTOMERS = 5000
N_PRODUCTS = 100
N_ORDERS = 20000

CITIES = [
    "Berlin", "Hamburg", "Munich", "Cologne", "Frankfurt", "Stuttgart",
    "Duesseldorf", "Leipzig", "Dortmund", "Essen", "Bremen", "Dresden",
    "Hanover", "Nuremberg", "Duisburg",
]
SEGMENTS = ["Standard", "Premium", "Business"]
SEGMENT_WEIGHTS = [0.65, 0.25, 0.10]
PAYMENT_METHODS = ["Credit Card", "PayPal", "Invoice", "Bank Transfer"]
ORDER_STATUSES = ["Completed", "Cancelled", "Returned"]
ORDER_STATUS_WEIGHTS = [0.86, 0.06, 0.08]

CATEGORIES = {
    "Smartphones": {"price_range": (299, 1399), "margin": (0.22, 0.32), "weight": 0.30},
    "Laptops": {"price_range": (499, 2499), "margin": (0.18, 0.28), "weight": 0.22},
    "Tablets": {"price_range": (199, 999), "margin": (0.20, 0.30), "weight": 0.14},
    "Kopfhoerer": {"price_range": (29, 399), "margin": (0.30, 0.42), "weight": 0.14},
    "Smartwatches": {"price_range": (99, 649), "margin": (0.25, 0.35), "weight": 0.10},
    "Zubehoer": {"price_range": (9, 149), "margin": (0.45, 0.60), "weight": 0.10},
}

FIRST_NAMES = [
    "Anna", "Max", "Lena", "Paul", "Mia", "Ben", "Emma", "Leon", "Hannah",
    "Lukas", "Sophie", "Felix", "Laura", "Jonas", "Marie", "Tim", "Julia",
    "Finn", "Sarah", "Niklas", "Lea", "David", "Nina", "Tom", "Clara",
]
LAST_NAMES = [
    "Mueller", "Schmidt", "Schneider", "Fischer", "Weber", "Meyer", "Wagner",
    "Becker", "Schulz", "Hoffmann", "Koch", "Bauer", "Richter", "Klein",
    "Wolf", "Schroeder", "Neumann", "Schwarz", "Zimmermann", "Braun",
]

START_DATE = date(2023, 1, 1)
END_DATE = date(2025, 12, 31)


def random_date(start, end):
    delta = (end - start).days
    return start + timedelta(days=random.randint(0, delta))


def gen_customers():
    rows = []
    for cid in range(1, N_CUSTOMERS + 1):
        first = random.choice(FIRST_NAMES)
        last = random.choice(LAST_NAMES)
        segment = np.random.choice(SEGMENTS, p=SEGMENT_WEIGHTS)
        reg_date = random_date(START_DATE, END_DATE)
        rows.append({
            "customer_id": cid,
            "first_name": first,
            "last_name": last,
            "email": f"{first.lower()}.{last.lower()}{cid}@example.com",
            "city": random.choice(CITIES),
            "country": "Germany",
            "registration_date": reg_date.isoformat(),
            "customer_segment": segment,
        })
    return rows


def gen_products():
    rows = []
    pid = 101
    cats = list(CATEGORIES.keys())
    # ensure roughly proportional counts per category
    counts = {c: max(4, int(N_PRODUCTS * CATEGORIES[c]["weight"])) for c in cats}
    # adjust to hit exactly N_PRODUCTS
    diff = N_PRODUCTS - sum(counts.values())
    counts[cats[0]] += diff

    return_rate_boost_products = set()

    for cat, n in counts.items():
        lo, hi = CATEGORIES[cat]["price_range"]
        m_lo, m_hi = CATEGORIES[cat]["margin"]
        for i in range(n):
            sell = round(random.uniform(lo, hi), 2)
            margin = random.uniform(m_lo, m_hi)
            purchase = round(sell * (1 - margin), 2)
            launch = random_date(START_DATE, END_DATE)
            rows.append({
                "product_id": pid,
                "product_name": f"Nova{cat[:4]} {chr(65 + i % 26)}{i}",
                "category": cat,
                "purchase_price": purchase,
                "selling_price": sell,
                "launch_date": launch.isoformat(),
            })
            pid += 1

    # pick ~6% of products to have an elevated return rate (Trend 6)
    all_ids = [r["product_id"] for r in rows]
    n_high_return = max(1, int(len(all_ids) * 0.06))
    high_return_products = set(random.sample(all_ids, n_high_return))

    return rows, high_return_products


def year_weight(order_date):
    # Trend 1: revenue grows each year -> weight order volume by year
    weights = {2023: 1.0, 2024: 1.45, 2025: 1.9}
    return weights.get(order_date.year, 1.0)


def month_weight(order_date):
    # Trend 5: Nov/Dec seasonal spike
    if order_date.month in (11, 12):
        return 1.6
    if order_date.month in (1, 2):
        return 0.8
    return 1.0


def gen_orders_and_items(customers, products, high_return_products):
    orders = []
    order_items = []
    order_id = 1
    order_item_id = 1

    # Build a weighted pool of customer_ids so Premium customers order more (Trend 2)
    seg_multiplier = {"Standard": 1.0, "Premium": 1.8, "Business": 1.4}
    cust_weights = np.array([seg_multiplier[c["customer_segment"]] for c in customers], dtype=float)
    cust_weights = cust_weights / cust_weights.sum()
    cust_ids = [c["customer_id"] for c in customers]

    # products grouped for weighted category selection (Trend 3: smartphones high revenue)
    prod_by_cat = {}
    for p in products:
        prod_by_cat.setdefault(p["category"], []).append(p)
    cat_names = list(CATEGORIES.keys())
    cat_weights = [CATEGORIES[c]["weight"] for c in cat_names]

    # Generate order dates first, weighted toward later years / Nov-Dec
    total_days = (END_DATE - START_DATE).days
    candidate_dates = []
    d = START_DATE
    while d <= END_DATE:
        w = year_weight(d) * month_weight(d)
        candidate_dates.append((d, w))
        d += timedelta(days=1)
    dates, weights = zip(*candidate_dates)
    weights = np.array(weights, dtype=float)
    weights = weights / weights.sum()

    order_dates = np.random.choice(len(dates), size=N_ORDERS, p=weights)

    for i in range(N_ORDERS):
        odate = dates[order_dates[i]]
        cust_id = int(np.random.choice(cust_ids, p=cust_weights))
        payment = random.choice(PAYMENT_METHODS)

        # Pick this order's items FIRST, so order_status can react to
        # whether a high-return product is in the basket (Trend 6).
        n_items = random.randint(1, 5)
        chosen_cats = np.random.choice(cat_names, size=n_items, p=cat_weights)
        items_for_order = []
        contains_high_return_product = False
        for cat in chosen_cats:
            product = random.choice(prod_by_cat[cat])
            qty = random.randint(1, 3)
            # small price variation vs. catalog price (discounts etc.)
            unit_price = round(product["selling_price"] * random.uniform(0.9, 1.05), 2)
            items_for_order.append({
                "order_id": order_id,
                "product_id": product["product_id"],
                "quantity": qty,
                "unit_price": unit_price,
            })
            if product["product_id"] in high_return_products:
                contains_high_return_product = True

        # Trend 6: orders containing a flagged product are ~3x more likely
        # to come back as "Returned" (roughly doubles the effective return
        # rate for those specific products in the final data).
        if contains_high_return_product:
            status_weights = [0.78, 0.05, 0.17]  # Completed, Cancelled, Returned
        else:
            status_weights = ORDER_STATUS_WEIGHTS
        status = np.random.choice(ORDER_STATUSES, p=status_weights)

        orders.append({
            "order_id": order_id,
            "customer_id": cust_id,
            "order_date": odate.isoformat(),
            "payment_method": payment,
            "order_status": status,
        })

        for item in items_for_order:
            order_items.append({
                "order_item_id": order_item_id,
                "order_id": item["order_id"],
                "product_id": item["product_id"],
                "quantity": item["quantity"],
                "unit_price": item["unit_price"],
            })
            order_item_id += 1

        order_id += 1

    return orders, order_items


def write_csv(path, rows):
    if not rows:
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


def main():
    print("Generating customers...")
    customers = gen_customers()
    write_csv(os.path.join(OUT_DIR, "customers.csv"), customers)

    print("Generating products...")
    products, high_return_products = gen_products()
    write_csv(os.path.join(OUT_DIR, "products.csv"), products)

    print("Generating orders and order_items...")
    orders, order_items = gen_orders_and_items(customers, products, high_return_products)
    write_csv(os.path.join(OUT_DIR, "orders.csv"), orders)
    write_csv(os.path.join(OUT_DIR, "order_items.csv"), order_items)

    print(f"Done. customers={len(customers)}, products={len(products)}, "
          f"orders={len(orders)}, order_items={len(order_items)}")
    print(f"CSV files written to: {os.path.abspath(OUT_DIR)}")


if __name__ == "__main__":
    main()
