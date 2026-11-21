"""Approved OpenRouter models: mid-high range (Artificial Analysis green zone) with input <= 2 USD per million tokens.

An application can only run on one of these (per-application env var or Phoenix prompt version); anything else
falls back to OPENROUTER_MODEL. All of them support tools, images, JSON schema and reasoning on OpenRouter.
Prices are USD per million tokens (input, output) as of 2026-11-21; `make phoenix-openrouter` loads the live ones.
Plain data (no imports) so scripts can read it with runpy without the app's dependencies.
"""

APPROVED_MODELS = {
    "openai/gpt-6.2-sol": {"index": 57, "price": (2.0, 10.0), "use": "Best reasoning: orchestrator, grid design."},
    "openai/gpt-6.1-terra": {"index": 51, "price": (1.0, 5.0),
                             "use": "Half of Sol: safety analysis, study, soil model, consolidation."},
    "google/gemini-4-hydrogen": {"index": 54, "price": (1.5, 7.5), "use": "Strong vision: reading plans."},
    "anthropic/claude-haiku-5.5": {"index": 36, "price": (0.1, 0.5),
                                   "use": "High volume: document extraction, materials. Default model."},
    "meta/muse-ember": {"index": 36, "price": (0.1, 0.5), "use": "Alternative to Haiku at the same price."},
    "tencent/hy4": {"index": 35, "price": (0.42, 1.25), "use": "Cheap alternative, borderline of the range."},
}
