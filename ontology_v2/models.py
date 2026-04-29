from datetime import datetime, timezone
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from govuk_ai_accelerator_app import db


class V2OntologyRun(db.Model):
    __tablename__ = "v2_ontology_runs"

    run_id: Mapped[UUID] = mapped_column(sa.Uuid, primary_key=True)
    status: Mapped[str] = mapped_column(sa.Text, nullable=False)
    domain: Mapped[str] = mapped_column(sa.Text, nullable=False)
    tasks: Mapped[list[str]] = mapped_column(
        sa.ARRAY(sa.Text).with_variant(sa.JSON, "sqlite"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )