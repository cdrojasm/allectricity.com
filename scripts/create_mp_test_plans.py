"""Create the subscription plans in the Mercado Pago TEST seller account (it cannot see the production plans).

    python scripts/create_mp_test_plans.py 660312,162599,63000

Amounts are COP per month, aligned with MP_PLAN_NAMES. Each plan gets the tier name as external_reference
(the "Código de referencia" of the panel). Prints the MP_TEST_PLAN_IDS line to paste into .env. Uses only
MP_TEST_ACCESS_TOKEN: production plans are never touched.
"""

import os
import sys

import mercadopago


def main() -> None:
    names = [item.strip() for item in os.environ["MP_PLAN_NAMES"].split(",")]
    amounts = [float(item) for item in sys.argv[1].split(",")]
    if len(names) != len(amounts):
        raise SystemExit("Pass one COP amount per name in MP_PLAN_NAMES, in the same order")
    sdk = mercadopago.SDK(os.environ["MP_TEST_ACCESS_TOKEN"])
    back_url = (os.getenv("PUBLIC_APP_URL") or "https://localhost").rstrip("/") + "/plans"
    ids = []
    for name, amount in zip(names, amounts):
        result = sdk.plan().create({
            "reason": f"Allectricity {name.capitalize()}",
            "external_reference": name,
            "auto_recurring": {"frequency": 1, "frequency_type": "months", "transaction_amount": amount,
                               "currency_id": "COP"},
            "back_url": back_url,
        })
        plan = result.get("response") or {}
        if result.get("status") not in (200, 201) or not plan.get("id"):
            raise SystemExit(f"{name}: Mercado Pago answered {result.get('status')}: {plan}")
        ids.append(plan["id"])
        print(f"{name}: {plan['id']} ({amount:,.0f} COP/mes)")
    print("MP_TEST_PLAN_IDS=" + ",".join(ids))


if __name__ == "__main__":
    main()
