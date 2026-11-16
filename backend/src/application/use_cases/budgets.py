from src.application.use_cases.identity import now, uid, audit
from src.application.use_cases.identity_admin import require_record, privileged
from src.domain.identity import ServiceError


def check_budget_owner(actor, budget):
    if not actor.privileged and actor.user_id != budget["user_id"]:
        raise ServiceError(404, "Budget not found")


class Budgets:
    def __init__(self, store):
        self.store = store

    def create(self, actor, data):
        privileged(actor)
        with self.store.transaction(write=True) as db:
            require_record(db, "users", data["user_id"])
            record = db.add(
                "budget", id=uid(), **data, used_tokens=0, active=True, created_at=now()
            )
            audit(db, actor.user_id, "budget.create", record["id"])
            return record

    def update(self, actor, budget_id, data):
        privileged(actor)
        with self.store.transaction(write=True) as db:
            budget = require_record(db, "budget", budget_id)
            if data.get("total_tokens", budget["total_tokens"]) < budget["used_tokens"]:
                raise ServiceError(
                    409, "Token limit cannot be lower than consumed tokens"
                )
            db.change("budget", budget_id, **data)
            audit(db, actor.user_id, "budget.update", budget_id)
            return require_record(db, "budget", budget_id)

    def consume(self, actor, budget_id, data):
        privileged(actor)
        with self.store.transaction(write=True) as db:
            budget = require_record(db, "budget", budget_id)
            previous = db.one(
                "budget_usage",
                budget_id=budget_id,
                idempotency_key=data["idempotency_key"],
            )
            if previous:
                if any(previous[k] != v for k, v in data.items()):
                    raise ServiceError(
                        409, "Idempotency key was already used with different data"
                    )
                return previous
            total = data["input_tokens"] + data["output_tokens"]
            if (
                not budget["active"]
                or total <= 0
                or budget["used_tokens"] + total > budget["total_tokens"]
            ):
                raise ServiceError(409, "Budget inactive or insufficient tokens")
            # The store write transaction serializes the read-check-debit and ledger insert.
            db.change("budget", budget_id, used_tokens=budget["used_tokens"] + total)
            usage = db.add(
                "budget_usage",
                id=uid(),
                budget_id=budget_id,
                actor_id=actor.user_id,
                **data,
                total_tokens=total,
                created_at=now(),
            )
            audit(db, actor.user_id, "budget.consume", usage["id"])
            return usage

    def agent_capacity(self, user_id) -> dict:
        """Active budgets of the user and the largest remaining balance among them (a step debits one budget)."""
        with self.store.transaction() as db:
            budgets = db.many("budget", user_id=user_id, active=True, limit=None)
        remaining = max((budget["total_tokens"] - budget["used_tokens"] for budget in budgets), default=0)
        return {"budgets": len(budgets), "remaining": max(0, remaining)}

    def consume_agent_usage(self, user_id, project_id, run_id, step, model, input_tokens, output_tokens):
        """Debit an agent invocation from the user's active budget, if one has capacity."""
        total = int(input_tokens) + int(output_tokens)
        if total <= 0:
            return None
        key = f"agent:{run_id}:{step}:{model}"[:128]
        with self.store.transaction(write=True) as db:
            candidates = sorted(db.many("budget", user_id=user_id, active=True, limit=None),
                               key=lambda budget: budget["created_at"])
            for budget in candidates:
                previous = db.one("budget_usage", budget_id=budget["id"], idempotency_key=key)
                if previous:
                    return previous
                if budget["used_tokens"] + total > budget["total_tokens"]:
                    continue
                db.change("budget", budget["id"], used_tokens=budget["used_tokens"] + total)
                usage = db.add(
                    "budget_usage", id=uid(), budget_id=budget["id"], actor_id=user_id,
                    project_id=project_id, action="grounding_design_agent", model=model,
                    input_tokens=int(input_tokens), output_tokens=int(output_tokens), total_tokens=total,
                    idempotency_key=key, created_at=now(),
                )
                audit(db, user_id, "budget.consume", usage["id"])
                return usage
        return None
