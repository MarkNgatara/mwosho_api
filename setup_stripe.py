"""
Create Stripe Products + recurring Prices for all paid tiers, then write the
price IDs into .env.

Run from the backend dir with the venv python:
    venv\\Scripts\\python.exe setup_stripe.py

Reads STRIPE_SECRET_KEY from .env via app.config.
"""
import os
import re

import stripe

from app.config import settings

stripe.api_key = settings.STRIPE_SECRET_KEY

# (TIER, display name, usd_monthly, usd_yearly) — yearly = 10 x monthly.
# Keep amounts in sync with app/plans.py.
TIERS = [
    ("STARTER",      "Mwosho Starter",      9,  90),
    ("PROFESSIONAL", "Mwosho Professional", 19, 190),
    ("BUSINESS",     "Mwosho Business",     29, 290),
    ("GROWTH",       "Mwosho Growth",       59, 590),
    ("ENTERPRISE",   "Mwosho Enterprise",   99, 990),
]


def create_prices() -> dict:
    if not stripe.api_key:
        raise SystemExit("STRIPE_SECRET_KEY missing from .env")
    ids = {}
    for tier, name, monthly, yearly in TIERS:
        product = stripe.Product.create(name=name, description=f"{name} subscription")
        print(f"Product {name}: {product.id}")
        for cycle, interval, amount in (("MONTHLY", "month", monthly), ("YEARLY", "year", yearly)):
            price = stripe.Price.create(
                product=product.id,
                unit_amount=amount * 100,        # USD cents
                currency="usd",
                recurring={"interval": interval},
            )
            key = f"STRIPE_{tier}_PRICE_{cycle}"
            ids[key] = price.id
            print(f"  {key}={price.id}")
    return ids


def patch_env(ids: dict):
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    content = open(env_path, encoding="utf-8").read() if os.path.exists(env_path) else ""
    for key, val in ids.items():
        if re.search(rf"^{key}=.*$", content, flags=re.MULTILINE):
            content = re.sub(rf"^{key}=.*$", f"{key}={val}", content, flags=re.MULTILINE)
        else:
            content = content.rstrip("\n") + f"\n{key}={val}\n"
    with open(env_path, "w", encoding="utf-8") as f:
        f.write(content)
    print("\n.env updated with Stripe price IDs.")


def main():
    ids = create_prices()
    print("\n--- Stripe price IDs (also written to .env) ---")
    for k, v in ids.items():
        print(f"{k}={v}")
    patch_env(ids)


if __name__ == "__main__":
    main()
