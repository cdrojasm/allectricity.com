"""Persistence for immutable optimizer runs and their feasible alternatives."""

from sqlalchemy import insert, select, update

from src.infrastructure.persistence.identity_schema import optimizer_alternatives, optimizer_runs


class OptimizerRunRepository:
    """Project-scoped storage; the caller owns the surrounding transaction."""

    def __init__(self, connection):
        self.connection = connection

    def create_run(self, values):
        """Create a run with a frozen request/context snapshot."""
        self.connection.execute(insert(optimizer_runs).values(**values))
        return self.get_run(values["project_id"], values["id"])

    def get_run(self, project_id, run_id):
        row = self.connection.execute(
            select(optimizer_runs).where(
                optimizer_runs.c.project_id == project_id,
                optimizer_runs.c.id == run_id,
            )
        ).mappings().first()
        return dict(row) if row else None

    def get_run_by_id(self, run_id):
        """For the worker, which only receives the run id; routes always scope by project."""
        row = self.connection.execute(select(optimizer_runs).where(optimizer_runs.c.id == run_id)).mappings().first()
        return dict(row) if row else None

    def transition(self, project_id, run_id, from_statuses, values):
        """Change lifecycle fields only while the run is still in one of ``from_statuses``.

        Returns the updated run, or None when another writer moved it first (a cancellation racing a
        worker that finishes, say), so a late writer never overwrites a terminal state.
        """
        allowed = {"status", "result_summary", "error", "updated_at"}
        changes = {key: value for key, value in values.items() if key in allowed}
        moved = self.connection.execute(
            update(optimizer_runs)
            .where(optimizer_runs.c.project_id == project_id, optimizer_runs.c.id == run_id,
                   optimizer_runs.c.status.in_(tuple(from_statuses)))
            .values(**changes)
        ).rowcount
        return self.get_run(project_id, run_id) if moved else None

    def count_active_runs(self, project_id, algorithm):
        """Queued or running runs of one algorithm in the project."""
        rows = self.connection.execute(
            select(optimizer_runs.c.request_snapshot).where(
                optimizer_runs.c.project_id == project_id,
                optimizer_runs.c.status.in_(("queued", "running")))).all()
        return sum(1 for (snapshot,) in rows if (snapshot or {}).get("algorithm") == algorithm)

    def list_runs(self, project_id, limit=50):
        rows = self.connection.execute(
            select(optimizer_runs)
            .where(optimizer_runs.c.project_id == project_id)
            .order_by(optimizer_runs.c.created_at.desc(), optimizer_runs.c.id.desc())
            .limit(limit)
        ).mappings()
        return [dict(row) for row in rows]

    def update_run(self, project_id, run_id, values):
        """Update lifecycle/result fields while retaining the original request snapshot."""
        allowed = {"status", "result_summary", "error", "updated_at"}
        changes = {key: value for key, value in values.items() if key in allowed}
        if not changes:
            return self.get_run(project_id, run_id)
        self.connection.execute(
            update(optimizer_runs)
            .where(optimizer_runs.c.project_id == project_id, optimizer_runs.c.id == run_id)
            .values(**changes)
        )
        return self.get_run(project_id, run_id)

    def add_alternatives(self, project_id, run_id, alternatives):
        """Persist feasible candidates only, retaining complete candidate/evaluation snapshots.

        Each alternative has ``candidate_sha256``, ``candidate_snapshot`` and
        ``evaluation_snapshot``. The latter should carry construction, electrical/physical
        feasibility, cost breakdown and provenance. Rank may be omitted when no single
        comparable objective exists (for example, mixed currencies).
        """
        run = self.get_run(project_id, run_id)
        if run is None:
            raise ValueError("optimizer run does not exist in this project")
        rows = []
        for alternative in alternatives:
            candidate = alternative["candidate_snapshot"]
            evaluation = alternative["evaluation_snapshot"]
            if not isinstance(candidate, dict) or not isinstance(evaluation, dict):
                raise ValueError("alternative snapshots must be JSON objects")
            safety = evaluation.get("safety")
            explicitly_feasible = (
                evaluation.get("feasible") is True
                or (isinstance(safety, dict) and safety.get("Feasible") is True)
            )
            if not explicitly_feasible:
                raise ValueError("only explicitly feasible alternatives can be persisted")
            rows.append({
                "id": alternative["id"],
                "run_id": run_id,
                "project_id": project_id,
                "candidate_sha256": alternative["candidate_sha256"],
                "rank": alternative.get("rank"),
                "recommended": bool(alternative.get("recommended", False)),
                "candidate_snapshot": candidate,
                "evaluation_snapshot": evaluation,
                "created_at": alternative["created_at"],
            })
        if rows:
            self.connection.execute(insert(optimizer_alternatives), rows)
        return self.list_alternatives(project_id, run_id)

    def list_alternatives(self, project_id, run_id):
        rows = self.connection.execute(
            select(optimizer_alternatives)
            .where(
                optimizer_alternatives.c.project_id == project_id,
                optimizer_alternatives.c.run_id == run_id,
            )
            .order_by(optimizer_alternatives.c.rank.is_(None),
                     optimizer_alternatives.c.rank, optimizer_alternatives.c.id)
        ).mappings()
        return [dict(row) for row in rows]

