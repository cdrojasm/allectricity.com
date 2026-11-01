"""Versioned global constraint profiles and project-pinned profile selections."""

from sqlalchemy import (
    BigInteger, CheckConstraint, Column, ForeignKey, ForeignKeyConstraint,
    Index, Integer, JSON, String, Table, delete, func, insert, select, update,
)

from src.infrastructure.persistence.identity_schema import metadata


constraint_profiles = Table(
    "constraint_profiles",
    metadata,
    Column("profile_id", String(80), primary_key=True),
    Column("created_by", String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
    Column("created_at", BigInteger, nullable=False),
)

constraint_profile_versions = Table(
    "constraint_profile_versions",
    metadata,
    Column("profile_id", String(80), ForeignKey("constraint_profiles.profile_id", ondelete="CASCADE"), primary_key=True),
    Column("version", Integer, primary_key=True),
    Column("status", String(16), nullable=False),
    Column("definition", JSON, nullable=False),
    Column("created_by", String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
    Column("reviewed_by", String(36), ForeignKey("users.id", ondelete="RESTRICT")),
    Column("retired_by", String(36), ForeignKey("users.id", ondelete="RESTRICT")),
    Column("created_at", BigInteger, nullable=False),
    Column("reviewed_at", BigInteger),
    Column("retired_at", BigInteger),
    CheckConstraint("status IN ('draft', 'reviewed', 'retired')", name="ck_constraint_profile_version_status"),
)
Index("ix_constraint_profile_versions_status", constraint_profile_versions.c.status)

project_constraint_profiles = Table(
    "project_constraint_profiles",
    metadata,
    Column("project_id", String(36), ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True),
    Column("profile_id", String(80), primary_key=True),
    Column("profile_version", Integer, nullable=False),
    Column("selected_by", String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
    Column("selected_at", BigInteger, nullable=False),
    ForeignKeyConstraint(
        ["profile_id", "profile_version"],
        ["constraint_profile_versions.profile_id", "constraint_profile_versions.version"],
        ondelete="RESTRICT",
        name="fk_project_constraint_profile_version",
    ),
)
Index("ix_project_constraint_profiles_profile", project_constraint_profiles.c.profile_id)


class ConstraintProfileRepository:
    def __init__(self, connection):
        self.connection = connection

    def create_profile(self, profile_id, actor_id, definition, now):
        self.connection.execute(insert(constraint_profiles).values(
            profile_id=profile_id, created_by=actor_id, created_at=now,
        ))
        return self.create_version(profile_id, 1, definition, actor_id, now)

    def create_version(self, profile_id, version, definition, actor_id, now):
        self.connection.execute(insert(constraint_profile_versions).values(
            profile_id=profile_id, version=version, status="draft", definition=definition,
            created_by=actor_id, reviewed_by=None, retired_by=None,
            created_at=now, reviewed_at=None, retired_at=None,
        ))
        return self.get_version(profile_id, version)

    def get_version(self, profile_id, version):
        row = self.connection.execute(
            select(constraint_profile_versions).where(
                constraint_profile_versions.c.profile_id == profile_id,
                constraint_profile_versions.c.version == version,
            )
        ).mappings().first()
        return dict(row) if row else None

    def latest_versions(self):
        latest = select(
            constraint_profile_versions.c.profile_id,
            func.max(constraint_profile_versions.c.version).label("version"),
        ).group_by(constraint_profile_versions.c.profile_id).subquery()
        rows = self.connection.execute(
            select(constraint_profile_versions).join(
                latest,
                (constraint_profile_versions.c.profile_id == latest.c.profile_id)
                & (constraint_profile_versions.c.version == latest.c.version),
            ).order_by(constraint_profile_versions.c.profile_id)
        ).mappings()
        return [dict(row) for row in rows]

    def all_versions(self):
        rows = self.connection.execute(
            select(constraint_profile_versions).order_by(
                constraint_profile_versions.c.profile_id,
                constraint_profile_versions.c.version.desc(),
            )
        ).mappings()
        return [dict(row) for row in rows]

    def next_version(self, profile_id):
        current = self.connection.execute(
            select(func.max(constraint_profile_versions.c.version)).where(
                constraint_profile_versions.c.profile_id == profile_id,
            )
        ).scalar_one_or_none()
        return (current or 0) + 1

    def review(self, profile_id, version, actor_id, now):
        self.connection.execute(update(constraint_profile_versions).where(
            constraint_profile_versions.c.profile_id == profile_id,
            constraint_profile_versions.c.version == version,
            constraint_profile_versions.c.status == "draft",
        ).values(status="reviewed", reviewed_by=actor_id, reviewed_at=now))
        return self.get_version(profile_id, version)

    def retire(self, profile_id, version, actor_id, now):
        self.connection.execute(update(constraint_profile_versions).where(
            constraint_profile_versions.c.profile_id == profile_id,
            constraint_profile_versions.c.version == version,
            constraint_profile_versions.c.status == "reviewed",
        ).values(status="retired", retired_by=actor_id, retired_at=now))
        return self.get_version(profile_id, version)

    def selected(self, project_id):
        rows = self.connection.execute(
            select(project_constraint_profiles, constraint_profile_versions.c.status,
                   constraint_profile_versions.c.definition)
            .join(constraint_profile_versions,
                  (constraint_profile_versions.c.profile_id == project_constraint_profiles.c.profile_id)
                  & (constraint_profile_versions.c.version == project_constraint_profiles.c.profile_version))
            .where(project_constraint_profiles.c.project_id == project_id)
            .order_by(project_constraint_profiles.c.profile_id)
        ).mappings()
        return [dict(row) for row in rows]

    def select_for_project(self, project_id, selections, actor_id, now):
        self.connection.execute(delete(project_constraint_profiles).where(
            project_constraint_profiles.c.project_id == project_id,
        ))
        if selections:
            self.connection.execute(insert(project_constraint_profiles), [
                {"project_id": project_id, "profile_id": item["profile_id"],
                 "profile_version": item["version"], "selected_by": actor_id,
                 "selected_at": now}
                for item in selections
            ])
        return self.selected(project_id)
