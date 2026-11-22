"""Approved OpenRouter models. An application can only run on one of these (per-application env var or Phoenix
prompt version); anything else falls back to OPENROUTER_MODEL.

- APPROVED_MODELS ("mid-high"): Artificial Analysis green zone with input <= 2 USD per million tokens; the ones in use.
- Chinese labs ("option"): available to switch to, not assigned to any application. Latest strong version and the
  cheapest current one of each lab; `index` is the Artificial Analysis index when it appears on the chart.
All of them support tools and JSON output on OpenRouter; "vision": False ones cannot read plans (spat-plan-vision).
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

    # Chinese labs: options only.
    "xiaomi/mimo-v2.6-pro": {"index": 30, "price": (0.435, 0.87), "group": "option", "use": "Xiaomi MiMo V2.6 Pro."},
    "xiaomi/mimo-v2.6-flash": {"index": None, "price": (0.14, 0.28), "group": "option", "use": "Cheapest MiMo."},
    "minimax/minimax-m3": {"index": None, "price": (0.30, 1.20), "group": "option", "use": "MiniMax M3."},
    "minimax/minimax-m3.1-flash": {"index": 29, "price": (0.075, 0.30), "group": "option", "use": "Cheapest MiniMax."},
    "moonshotai/kimi-k3.1-pro": {"index": 46, "price": (0.253, 8.80), "group": "option",
                                 "use": "Kimi K3.1 Pro; expensive output."},
    "moonshotai/kimi-k2.5": {"index": None, "price": (0.50, 2.50), "group": "option", "use": "Cheapest current Kimi."},
    "deepseek/deepseek-v4-pro": {"index": None, "price": (0.90, 1.50), "group": "option", "vision": False,
                                 "use": "DeepSeek V4 Pro."},
    "deepseek/deepseek-v4.1-flash-1017": {"index": 32, "price": (0.15, 0.60), "group": "option",
                                          "use": "DeepSeek V4.1 Flash (charted snapshot)."},
    "deepseek/deepseek-v4.1-flash": {"index": None, "price": (0.05, 0.199), "group": "option",
                                     "use": "Cheapest DeepSeek."},
    "qwen/qwen4-max": {"index": 43, "price": (1.425, 4.275), "group": "option", "use": "Qwen4 Max."},
    "qwen/qwen3.8-flash": {"index": None, "price": (0.15, 0.47), "group": "option", "use": "Qwen 3.8 Flash."},
    "qwen/qwen3.7-flash": {"index": None, "price": (0.03, 0.13), "group": "option", "use": "Cheapest Qwen."},
    "z-ai/glm-5.3": {"index": 31, "price": (0.07, 1.40), "group": "option", "vision": False, "use": "GLM-5.3."},
    "z-ai/glm-5.3-flash": {"index": None, "price": (0.04, 0.078), "group": "option", "use": "Cheapest GLM."},
    "tencent/hy4-flash": {"index": None, "price": (0.035, 0.14), "group": "option", "use": "Cheapest Hunyuan."},
    "bytedance-seed/seed-2-1-turbo": {"index": None, "price": (0.50, 2.50), "group": "option",
                                      "use": "ByteDance Seed 2.1 Turbo."},
    "bytedance-seed/seed-2.0-mini": {"index": None, "price": (0.10, 0.40), "group": "option",
                                     "use": "Cheapest Seed."},
    "stepfun/step-3.7-flash": {"index": None, "price": (0.20, 1.15), "group": "option", "use": "StepFun Step 3.7."},
}
