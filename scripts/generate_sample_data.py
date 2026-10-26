"""Generate the bundled sample dataset (sample-data/retail_sales_2025.csv).

The data is synthetic but shaped like a real retail order export, including the
kinds of problems real files have, so every DataLens feature has something
genuine to find:

* seasonality (Nov/Dec peak) and a West-region slump in Q3
* customer ratings that fall as shipping time rises (a real negative correlation)
* ~1.2% of orders with missing revenue, ~9% with no rating
* a handful of exact duplicate rows, refunds (negative revenue) and bulk orders

Run:  python scripts/generate_sample_data.py
The seed is fixed, so the output is reproducible.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

SEED = 20251026
N_ORDERS = 4200
OUT = Path(__file__).resolve().parents[1] / "sample-data" / "retail_sales_2025.csv"

PRODUCTS = {
    "Electronics": [("Wireless Earbuds", 79), ("Smartwatch", 199), ("Bluetooth Speaker", 59), ("4K Monitor", 329)],
    "Home & Kitchen": [("Air Fryer", 119), ("Espresso Machine", 249), ("Blender", 69)],
    "Office": [("Ergonomic Chair", 289), ("Standing Desk", 449), ("Desk Lamp", 39)],
    "Apparel": [("Running Shoes", 95), ("Rain Jacket", 129), ("Backpack", 65)],
}
REGIONS = ["North", "South", "East", "West", "Central"]
REGION_W = [0.22, 0.19, 0.21, 0.24, 0.14]
CHANNELS = ["Online", "Retail Store", "Partner"]
CHANNEL_W = [0.52, 0.33, 0.15]
MONTH_W = np.array([0.8, 0.75, 0.85, 0.9, 0.95, 0.95, 0.9, 0.95, 1.0, 1.05, 1.45, 1.6])


def main() -> None:
    rng = np.random.default_rng(SEED)

    # Order dates weighted by month seasonality.
    days = pd.date_range("2025-01-01", "2025-12-31", freq="D")
    day_w = MONTH_W[days.month - 1]
    day_w = day_w / day_w.sum()
    dates = rng.choice(days, size=N_ORDERS, p=day_w)
    dates = np.sort(dates)

    regions = rng.choice(REGIONS, size=N_ORDERS, p=REGION_W)
    # West slump: in Q3 drop a share of West orders by reassigning them elsewhere.
    months = pd.DatetimeIndex(dates).month
    west_q3 = (regions == "West") & (months >= 7) & (months <= 9)
    move = west_q3 & (rng.random(N_ORDERS) < 0.45)
    regions[move] = rng.choice(["North", "South", "East", "Central"], size=move.sum())

    channels = rng.choice(CHANNELS, size=N_ORDERS, p=CHANNEL_W)
    categories = rng.choice(list(PRODUCTS), size=N_ORDERS, p=[0.34, 0.24, 0.22, 0.20])

    products, prices = [], []
    for cat in categories:
        name, price = PRODUCTS[cat][rng.integers(len(PRODUCTS[cat]))]
        products.append(name)
        prices.append(price)
    prices = np.array(prices, dtype=float)

    units = rng.poisson(1.6, size=N_ORDERS) + 1
    discount = rng.choice([0, 0.05, 0.10, 0.15, 0.20], size=N_ORDERS, p=[0.45, 0.2, 0.18, 0.1, 0.07])
    # West also discounted harder during its slump.
    discount = np.where(west_q3 & ~move, np.minimum(discount + 0.05, 0.25), discount)

    base_ship = np.select([channels == "Online", channels == "Partner"], [4.0, 5.5], default=1.5)
    shipping_days = np.clip(np.round(base_ship + rng.normal(0, 1.6, N_ORDERS)), 1, 12).astype(int)

    rating_raw = 4.75 - 0.22 * shipping_days + rng.normal(0, 0.7, N_ORDERS)
    rating = np.clip(np.round(rating_raw), 1, 5)

    revenue = np.round(units * prices * (1 - discount), 2)

    df = pd.DataFrame(
        {
            "order_id": [f"ORD-{10001 + i}" for i in range(N_ORDERS)],
            "order_date": pd.DatetimeIndex(dates).strftime("%Y-%m-%d"),
            "region": regions,
            "channel": channels,
            "category": categories,
            "product": products,
            "units": units,
            "unit_price": prices,
            "discount": discount,
            "revenue": revenue,
            "shipping_days": shipping_days,
            "customer_rating": rating,
        }
    )

    # Bulk orders (genuine outliers).
    bulk = rng.choice(N_ORDERS, size=4, replace=False)
    df.loc[bulk, "units"] = rng.integers(40, 70, size=4)
    df.loc[bulk, "revenue"] = np.round(df.loc[bulk, "units"] * df.loc[bulk, "unit_price"] * 0.8, 2)

    # Refunds recorded as negative revenue.
    refunds = rng.choice(N_ORDERS, size=6, replace=False)
    df.loc[refunds, "revenue"] = -df.loc[refunds, "revenue"].abs()

    # Missing values.
    df.loc[rng.random(N_ORDERS) < 0.012, "revenue"] = np.nan
    df.loc[rng.random(N_ORDERS) < 0.09, "customer_rating"] = np.nan

    # Exact duplicate rows, as produced by a double export.
    dups = df.sample(n=17, random_state=SEED)
    df = pd.concat([df, dups]).sort_values(["order_date", "order_id"], kind="stable").reset_index(drop=True)

    df["customer_rating"] = df["customer_rating"].astype("Int64")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT, index=False)
    print(f"Wrote {len(df):,} rows to {OUT}")


if __name__ == "__main__":
    main()
