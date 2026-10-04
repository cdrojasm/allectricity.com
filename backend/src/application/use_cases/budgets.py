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
