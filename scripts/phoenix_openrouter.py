"""Register OpenRouter in Arize Phoenix: a custom provider plus every OpenRouter model with its price.

    PHOENIX_ENDPOINT=http://localhost:6016 [PHOENIX_API_KEY=...] OPENROUTER_API_KEY=... python3 scripts/phoenix_openrouter.py

- Custom provider "OpenRouter" (OpenAI SDK, base URL https://openrouter.ai/api/v1): the Playground can run any
  OpenRouter model by typing its id (Phoenix's model dropdown is a fixed list; it cannot be extended).
- Every model of https://openrouter.ai/api/v1/models becomes a Phoenix model named with its provider prefix
  (openai/gpt-6.2-sol, anthropic/claude-haiku-5.5, ...) and its prompt/completion/cache prices, so Phoenix
  shows the cost of every traced call. New models are added and changed prices updated on every run.
Standard library only; the OpenRouter key is sent to Phoenix (stored encrypted there) and never printed.
"""

import json
import os
import re
import sys
import urllib.request

OPENROUTER = "https://openrouter.ai/api/v1"
PROVIDER_NAME = "OpenRouter"
# Spans of the OpenAI SDK are tagged provider "openai"; prices must carry the same provider to be matched.
MODEL_PROVIDER = "openai"


def http(url, payload=None, headers=None):
    request = urllib.request.Request(url, data=None if payload is None else json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


class Phoenix:
    def __init__(self, endpoint, api_key):
        self.url = endpoint.rstrip("/") + "/graphql"
        self.headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

    def __call__(self, query, **variables):
        reply = http(self.url, {"query": query, "variables": variables}, self.headers)
        if reply.get("errors"):
            raise RuntimeError("; ".join(e.get("message", "") for e in reply["errors"]))
        return reply["data"]

    def all(self, field, selection):
        items, after = [], None
        while True:
            data = self(f"query($after: String) {{ {field}(first: 200, after: $after) {{ edges {{ node {{ {selection} }} }}"
                        " pageInfo { hasNextPage endCursor } } }", after=after)[field]
            items += [edge["node"] for edge in data["edges"]]
            if not data["pageInfo"]["hasNextPage"]:
                return items
            after = data["pageInfo"]["endCursor"]


def prices(model) -> list[dict]:
    pricing = model.get("pricing") or {}
    costs = []
    for field, token_type, kind in (("prompt", "input", "PROMPT"), ("completion", "output", "COMPLETION"),
                                    ("input_cache_read", "cache_read", "PROMPT"),
                                    ("input_cache_write", "cache_write", "PROMPT")):
        try:
            value = float(pricing.get(field) or 0) * 1_000_000
        except (TypeError, ValueError):
            continue
        if value > 0 or field in {"prompt", "completion"}:
            costs.append({"tokenType": token_type, "kind": kind, "costPerMillionTokens": round(max(value, 0), 6)})
    return costs


def ensure_provider(phoenix, openrouter_key):
    config = {"openai": {"openaiAuthenticationMethod": {"apiKey": openrouter_key},
                         "openaiClientKwargs": {"baseUrl": OPENROUTER},
                         "openaiApiType": "CHAT_COMPLETIONS"}}
    existing = [p for p in phoenix.all("generativeModelCustomProviders", "id name") if p["name"] == PROVIDER_NAME]
    if existing:
        phoenix("mutation($input: PatchGenerativeModelCustomProviderMutationInput!) {"
                " patchGenerativeModelCustomProvider(input: $input) { __typename } }",
                input={"id": existing[0]["id"], "clientConfig": config})
        print(f"Provider {PROVIDER_NAME}: updated")
    else:
        phoenix("mutation($input: CreateGenerativeModelCustomProviderMutationInput!) {"
                " createGenerativeModelCustomProvider(input: $input) { __typename } }",
                input={"name": PROVIDER_NAME, "provider": "OPENAI", "clientConfig": config,
                       "description": "OpenRouter (OpenAI-compatible); model ids carry their provider prefix."})
        print(f"Provider {PROVIDER_NAME}: created")


def sync_models(phoenix, models):
    current = {m["name"]: m for m in phoenix.all(
        "generativeModels", "id name kind provider tokenPrices { tokenType kind costPerMillionTokens }")
        if m["kind"] != "BUILT_IN"}
    added = updated = 0
    for model in models:
        name, costs = model["id"], prices(model)
        pattern = "^" + re.escape(name) + "$"
        known = current.get(name)
        if known is None:
            phoenix("mutation($input: CreateModelMutationInput!) { createModel(input: $input) { __typename } }",
                    input={"name": name, "provider": MODEL_PROVIDER, "namePattern": pattern, "costs": costs})
            added += 1
        else:
            have = sorted((p["tokenType"], p["kind"], round(p["costPerMillionTokens"], 6)) for p in known["tokenPrices"])
            want = sorted((c["tokenType"], c["kind"], c["costPerMillionTokens"]) for c in costs)
            if have != want or known["provider"] != MODEL_PROVIDER:
                phoenix("mutation($input: UpdateModelMutationInput!) { updateModel(input: $input) { __typename } }",
                        input={"id": known["id"], "name": name, "provider": MODEL_PROVIDER,
                               "namePattern": pattern, "costs": costs})
                updated += 1
    print(f"Models: {len(models)} in OpenRouter, {added} added, {updated} prices updated")


def main():
    endpoint = os.getenv("PHOENIX_ENDPOINT") or os.getenv("PHOENIX_COLLECTOR_ENDPOINT")
    openrouter_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not endpoint or not openrouter_key:
        sys.exit("Define PHOENIX_ENDPOINT and OPENROUTER_API_KEY")
    phoenix = Phoenix(endpoint, os.getenv("PHOENIX_API_KEY"))
    models = [m for m in http(OPENROUTER + "/models")["data"] if not m["id"].startswith("~")]
    ensure_provider(phoenix, openrouter_key)
    sync_models(phoenix, models)


if __name__ == "__main__":
    main()
