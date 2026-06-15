"""
Create the PayPal subscription product + plans for all paid tiers via the API,
then write the resulting plan IDs into .env.

Run from the backend dir with the venv python:
    venv\\Scripts\\python.exe setup_paypal_live.py

Credentials and environment (live vs sandbox) are read from .env via app.config,
so nothing secret is hard-coded here.
"""
import os
import re
import base64

import requests

from app.config import settings

CLIENT_ID     = settings.PAYPAL_CLIENT_ID
CLIENT_SECRET = settings.PAYPAL_CLIENT_SECRET
BASE          = "https://api-m.sandbox.paypal.com" if settings.PAYPAL_MODE == "sandbox" else "https://api-m.paypal.com"

# yearly = 10 x monthly (2 months free). Keep amounts in sync with app/plans.py.
PLANS = [
    {"name": "Mwosho Starter – Monthly",      "key": "PAYPAL_STARTER_PLAN_MONTHLY",      "amount": "9.00",   "cycle": "MONTH"},
    {"name": "Mwosho Starter – Yearly",       "key": "PAYPAL_STARTER_PLAN_YEARLY",       "amount": "90.00",  "cycle": "YEAR"},
    {"name": "Mwosho Professional – Monthly", "key": "PAYPAL_PROFESSIONAL_PLAN_MONTHLY", "amount": "19.00",  "cycle": "MONTH"},
    {"name": "Mwosho Professional – Yearly",  "key": "PAYPAL_PROFESSIONAL_PLAN_YEARLY",  "amount": "190.00", "cycle": "YEAR"},
    {"name": "Mwosho Business – Monthly",     "key": "PAYPAL_BUSINESS_PLAN_MONTHLY",     "amount": "29.00",  "cycle": "MONTH"},
    {"name": "Mwosho Business – Yearly",      "key": "PAYPAL_BUSINESS_PLAN_YEARLY",      "amount": "290.00", "cycle": "YEAR"},
    {"name": "Mwosho Growth – Monthly",       "key": "PAYPAL_GROWTH_PLAN_MONTHLY",       "amount": "59.00",  "cycle": "MONTH"},
    {"name": "Mwosho Growth – Yearly",        "key": "PAYPAL_GROWTH_PLAN_YEARLY",        "amount": "590.00", "cycle": "YEAR"},
    {"name": "Mwosho Enterprise – Monthly",   "key": "PAYPAL_ENTERPRISE_PLAN_MONTHLY",   "amount": "99.00",  "cycle": "MONTH"},
    {"name": "Mwosho Enterprise – Yearly",    "key": "PAYPAL_ENTERPRISE_PLAN_YEARLY",    "amount": "990.00", "cycle": "YEAR"},
]


def get_token() -> str:
    print(f"Getting PayPal {settings.PAYPAL_MODE} access token...")
    if not CLIENT_ID or not CLIENT_SECRET:
        raise SystemExit("PAYPAL_CLIENT_ID / PAYPAL_CLIENT_SECRET missing from .env")
    creds = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
    r = requests.post(
        f"{BASE}/v1/oauth2/token",
        headers={"Authorization": f"Basic {creds}", "Content-Type": "application/x-www-form-urlencoded"},
        data="grant_type=client_credentials",
        timeout=15,
    )
    r.raise_for_status()
    print("OK\n")
    return r.json()["access_token"]


def create_product(token: str) -> str:
    print("Creating product...")
    r = requests.post(
        f"{BASE}/v1/catalogs/products",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            # Stable idempotency key — re-running returns the SAME product instead of duplicating.
            "PayPal-Request-Id": "mwosho-product-v1",
        },
        json={
            "name":        "Mwosho Data Quality Platform",
            "description": "AI-powered data quality automation",
            "type":        "SERVICE",
            "category":    "SOFTWARE",
        },
        timeout=15,
    )
    if not r.ok:
        print(f"ERROR {r.status_code}: {r.text}")
        r.raise_for_status()
    prod_id = r.json()["id"]
    print(f"Product created: {prod_id}\n")
    return prod_id


def create_plans(token: str, product_id: str) -> dict:
    print("Creating subscription plans...")
    ids = {}
    for p in PLANS:
        r = requests.post(
            f"{BASE}/v1/billing/plans",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                # Stable per-plan idempotency key. Re-running won't create duplicates.
                # Bump the -v1 suffix when you change a price, so PayPal makes a NEW plan
                # (plan prices are immutable — you can't edit a price by re-creating).
                "PayPal-Request-Id": f"mwosho-{p['key'].lower()}-v1",
            },
            json={
                "product_id":   product_id,
                "name":         p["name"],
                "status":       "ACTIVE",
                "billing_cycles": [
                    {
                        "frequency":        {"interval_unit": p["cycle"], "interval_count": 1},
                        "tenure_type":      "REGULAR",
                        "sequence":         1,
                        "total_cycles":     0,
                        "pricing_scheme":   {"fixed_price": {"value": p["amount"], "currency_code": "USD"}},
                    }
                ],
                "payment_preferences": {
                    "auto_bill_outstanding":     True,
                    "setup_fee":                 {"value": "0", "currency_code": "USD"},
                    "setup_fee_failure_action":  "CONTINUE",
                    "payment_failure_threshold": 3,
                },
            },
            timeout=15,
        )
        r.raise_for_status()
        plan_id = r.json()["id"]
        ids[p["key"]] = plan_id
        print(f"  {p['name']}: {plan_id}")
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
    print("\n.env updated with plan IDs.")


def main():
    token      = get_token()
    product_id = create_product(token)
    ids        = create_plans(token, product_id)

    print("\n--- Plan IDs (also written to .env) ---")
    for k, v in ids.items():
        print(f"{k}={v}")

    patch_env(ids)


if __name__ == "__main__":
    main()
