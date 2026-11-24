"""Persist project quotations and immutable editable snapshots."""

from sqlalchemy import BigInteger, CheckConstraint, Column, ForeignKey, Integer, JSON, String, Table, UniqueConstraint, select, update

from src.infrastructure.persistence.identity_schema import metadata


quotations = Table(
    "quotations", metadata,
    Column("id", String(36), primary_key=True),
    Column("project_id", String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
    Column("created_by", String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
    Column("number", String(40), nullable=False),
    Column("title", String(240), nullable=False),
    Column("status", String(20), nullable=False),
    Column("version", Integer, nullable=False),
    Column("valid_until", BigInteger),
    Column("currency", String(3), nullable=False),
    Column("content", JSON, nullable=False),
    Column("totals", JSON, nullable=False),
    Column("created_at", BigInteger, nullable=False),
    Column("updated_at", BigInteger, nullable=False),
    CheckConstraint("status IN ('draft', 'sent', 'accepted', 'rejected', 'expired')", name="ck_quotation_status"),
    CheckConstraint("length(currency) = 3", name="ck_quotation_currency"),
)

quotation_versions = Table(
    "quotation_versions", metadata,
    Column("id", String(36), primary_key=True),
    Column("quotation_id", String(36), ForeignKey("quotations.id", ondelete="CASCADE"), nullable=False),
    Column("project_id", String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
    Column("version", Integer, nullable=False),
    Column("snapshot", JSON, nullable=False),
    Column("created_by", String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
    Column("created_at", BigInteger, nullable=False),
)

quotation_templates = Table(
    "quotation_templates", metadata,
    Column("id", String(36), primary_key=True),
    Column("owner_id", String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("name", String(160), nullable=False),
    Column("content", JSON, nullable=False),
    Column("created_at", BigInteger, nullable=False),
    Column("updated_at", BigInteger, nullable=False),
    UniqueConstraint("owner_id", "name", name="uq_quotation_template_owner_name"),
)


class QuotationRepository:
    def __init__(self, connection):
        self.connection = connection

    def get(self, project_id, quotation_id):
        row = self.connection.execute(select(quotations).where(
            quotations.c.project_id == project_id, quotations.c.id == quotation_id,
        )).mappings().first()
        return dict(row) if row else None

    def list(self, project_id):
        rows = self.connection.execute(select(quotations).where(quotations.c.project_id == project_id)
            .order_by(quotations.c.updated_at.desc(), quotations.c.id)).mappings()
        return [dict(row) for row in rows]

    def insert(self, values):
        self.connection.execute(quotations.insert().values(**values))
        return self.get(values["project_id"], values["id"])

    def update(self, project_id, quotation_id, values):
        self.connection.execute(update(quotations).where(quotations.c.project_id == project_id,
            quotations.c.id == quotation_id).values(**values))
        return self.get(project_id, quotation_id)

    def add_version(self, snapshot):
        self.connection.execute(quotation_versions.insert().values(**snapshot))

    def versions(self, project_id, quotation_id):
        rows = self.connection.execute(select(quotation_versions).where(
            quotation_versions.c.project_id == project_id, quotation_versions.c.quotation_id == quotation_id,
        ).order_by(quotation_versions.c.version.desc())).mappings()
        return [dict(row) for row in rows]


class QuotationTemplateRepository:
    def __init__(self, connection):
        self.connection = connection

    def list(self, owner_id):
        rows = self.connection.execute(select(quotation_templates).where(
            quotation_templates.c.owner_id == owner_id,
        ).order_by(quotation_templates.c.updated_at.desc(), quotation_templates.c.id)).mappings()
        return [dict(row) for row in rows]

    def get(self, owner_id, template_id):
        row = self.connection.execute(select(quotation_templates).where(
            quotation_templates.c.owner_id == owner_id, quotation_templates.c.id == template_id,
        )).mappings().first()
        return dict(row) if row else None

    def insert(self, values):
        self.connection.execute(quotation_templates.insert().values(**values))
        return self.get(values["owner_id"], values["id"])

    def delete(self, owner_id, template_id):
        row = self.get(owner_id, template_id)
        if row:
            self.connection.execute(quotation_templates.delete().where(
                quotation_templates.c.owner_id == owner_id, quotation_templates.c.id == template_id,
            ))
        return row
