"""Rebuild the unified customer domain behind a fail-closed cutover fence.

Revision ID: 126
Revises: 125_invoice_integration

This revision intentionally has no downgrade.  It clears the approved legacy
customer business scope and rebuilds it; the maintenance evidence and exact
Agent closure are therefore part of the migration contract, not operator notes.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from itertools import islice
from pathlib import Path
from typing import Any, Mapping

from alembic import context, op
import sqlalchemy as sa
from sqlalchemy import MetaData, Table
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Session

from app.core.time import beijing_now_aware, to_beijing_naive
from app.customer.cutover_service import (
    AGENT_ID_QUERY_CHUNK_SIZE,
    CUTOVER_EVIDENCE_ROOT,
    AgentHistoryClosure,
    AgentPreservationSnapshot,
    CutoverGuardError,
    _reflected_physical_schema_signature,
    bootstrap_migration_fence,
    canonical_json_bytes,
    compare_physical_schema_signature,
    load_bound_customer_cutover_evidence,
    load_writer_privilege_revocation_evidence,
    migration_preflight,
    resolve_agent_history_closure,
    snapshot_unrelated_agent_rows,
    validate_incoming_retired_foreign_keys,
    validate_mysql_writer_privilege_gate,
    validate_target_profile_policy_backfill_against_live_rows,
    validate_target_profile_policy_backfill_artifact,
    verify_agent_history_removed,
    verify_target_profile_post_state,
    verify_unrelated_unchanged,
)


revision = "126"
down_revision = "125_invoice_integration"
branch_labels = None
depends_on = None


CORE_TABLE_NAMES = (
    "ark_customer_accounts",
    "ark_customer_names",
    "ark_customer_external_identities",
    "ark_customer_relationships",
    "ark_customer_assignments",
    "ark_customer_contacts",
    "ark_customer_contact_points",
    "ark_customer_contact_relationships",
    "ark_customer_source_records",
    "ark_customer_facts",
    "ark_customer_events",
    "ark_customer_annotations",
    "ark_customer_qualification_reviews",
    "ark_customer_profile_versions",
    "ark_customer_agent_contexts",
    "ark_customer_conversations",
    "ark_customer_messages",
    "ark_customer_conversation_analyses",
    "ark_customer_orders",
    "ark_customer_order_items",
    "ark_customer_research_tasks",
    "ark_customer_sync_cursors",
    "ark_customer_fact_evidence_links",
    "ark_customer_fact_conflicts",
    "ark_customer_list_projections",
    "ark_customer_change_proposals",
    "ark_customer_agent_run_scopes",
    "ark_customer_suppression_registry",
    "ark_customer_resolution_keys",
    "ark_customer_target_matches",
    "ark_customer_acquisition_attributions",
)
WORKFLOW_TABLE_NAMES = (
    "ark_sales_search_jobs",
    "ark_sales_search_results",
    "ark_sales_search_result_sources",
    "ark_sales_public_pool_batches",
    "ark_customer_opportunities",
    "ark_customer_opportunity_events",
    "ark_customer_actions",
)
TARGET_TABLE_NAMES = CORE_TABLE_NAMES + WORKFLOW_TABLE_NAMES

RETIRED_OR_REBUILT_TABLES = (
    "ark_sales_search_jobs",
    "ark_sales_search_results",
    "ark_sales_search_result_sources",
    "ark_sales_companies",
    "ark_sales_contacts",
    "ark_sales_research_subjects",
    "ark_sales_public_pool_batches",
    "ark_sales_public_pool_tasks",
    "ark_sales_deal_assessments",
    "ark_sales_research_runs",
    "ark_sales_research_facts",
    "ark_inquiry_import_batches",
    "ark_customer_opportunities",
    "ark_customer_opportunity_events",
    "ark_customer_profiles",
    "ark_customer_profile_events",
    "ark_customer_actions",
)
OPTIONAL_RETIRED_TABLES = frozenset({"ark_sales_search_result_sources"})
DROP_ORDER = (
    "ark_customer_actions",
    "ark_customer_profile_events",
    "ark_customer_opportunity_events",
    "ark_sales_deal_assessments",
    "ark_sales_public_pool_tasks",
    "ark_sales_search_result_sources",
    "ark_sales_search_results",
    "ark_sales_contacts",
    "ark_sales_research_facts",
    "ark_sales_research_runs",
    "ark_sales_public_pool_batches",
    "ark_sales_research_subjects",
    "ark_sales_companies",
    "ark_sales_search_jobs",
    "ark_customer_opportunities",
    "ark_customer_profiles",
    "ark_inquiry_import_batches",
)
AGENT_DELETE_ORDER = (
    ("ark_agent_artifacts", "artifact_ids"),
    ("ark_agent_events", "event_ids"),
    ("ark_agent_runs", "run_ids"),
    ("ark_agent_sessions", "session_ids"),
)
TARGET_PROFILE_COLUMNS = {
    "policy_version": "策略版本",
    "policy_json": "target_profile_policy_v1阈值、权重、研究与领取规则",
    "policy_snapshot_hash": "规范快照SHA-256",
    "last_improvement_artifact_id": "最近人工批准改进Artifact",
    "policy_applied_at": "策略生效北京时间",
}

CHAR64 = sa.String(64).with_variant(mysql.CHAR(64), "mysql")

# These literals pin the complete 38-table contract and the revision-owned
# resource bytes; migration replay never reads mutable runtime ORM metadata.
FROZEN_TARGET_SCHEMA_SHA256 = (
    "be44793c7532cb572397bbc595dd874c774b960f06cf0186133119783c8bfc95"
)
FROZEN_SCHEMA_RESOURCE_SHA256 = (
    "34672f9cf0c0e0e3d6b6707fb545f3e08b3b05dc6db783f6837defef6733a618"
)
FROZEN_SCHEMA_RESOURCE_PATH = Path(__file__).with_name(
    "126_unified_customer_domain_schema.json"
)


def _validate_frozen_customer_contract(contract: Mapping[str, Any]) -> str:
    if set(contract) != {
        "schema_version",
        "migration_revision",
        "tables",
        "contract_sha256",
    } or contract.get("schema_version") != 1 or contract.get(
        "migration_revision"
    ) != revision:
        raise CutoverGuardError("revision 126 frozen customer schema is incomplete")
    tables = contract.get("tables")
    if not isinstance(tables, Mapping) or set(tables) != set(TARGET_TABLE_NAMES):
        raise CutoverGuardError("revision 126 frozen customer table set is invalid")
    categories = {
        "columns",
        "primary_key",
        "unique_constraints",
        "indexes",
        "foreign_keys",
        "checks",
        "table_comment",
    }
    for table_name, signature in tables.items():
        if (
            not isinstance(signature, Mapping)
            or set(signature) != categories
            or not isinstance(signature.get("table_comment"), str)
            or not signature["table_comment"].strip()
        ):
            raise CutoverGuardError(
                f"revision 126 frozen schema is incomplete for {table_name}"
            )
        columns = signature.get("columns")
        if not isinstance(columns, list) or not columns:
            raise CutoverGuardError(
                f"revision 126 frozen columns are invalid for {table_name}"
            )
        for column in columns:
            if (
                not isinstance(column, Mapping)
                or not isinstance(column.get("comment"), str)
                or not column["comment"].strip()
                or (
                    column.get("computed") is not None
                    and (
                        column.get("default") is not None
                        or column["computed"].get("persisted") is not True
                    )
                )
            ):
                raise CutoverGuardError(
                    f"revision 126 frozen column is invalid for {table_name}"
                )
    payload = {key: value for key, value in contract.items() if key != "contract_sha256"}
    digest = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
    if digest != contract.get("contract_sha256"):
        raise CutoverGuardError("revision 126 frozen customer schema SHA-256 mismatch")
    return digest


def _load_frozen_schema_resource() -> dict[str, Any]:
    try:
        raw = FROZEN_SCHEMA_RESOURCE_PATH.read_bytes()
        resource = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise CutoverGuardError("cannot read revision 126 frozen schema resource") from exc
    expected_raw = (
        json.dumps(
            resource,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            separators=(",", ": "),
        )
        + "\n"
    ).encode("utf-8")
    normalized_raw = raw.replace(b"\r\n", b"\n")
    if normalized_raw != expected_raw or hashlib.sha256(expected_raw).hexdigest() != (
        FROZEN_SCHEMA_RESOURCE_SHA256
    ):
        raise CutoverGuardError("revision 126 frozen schema resource hash mismatch")
    if set(resource) != {
        "resource_schema_version",
        "migration_revision",
        "customer_domain_physical_contract",
        "target_profile_physical_contract",
    } or resource.get("resource_schema_version") != 1 or resource.get(
        "migration_revision"
    ) != revision:
        raise CutoverGuardError("revision 126 frozen schema resource is invalid")
    customer_contract = resource["customer_domain_physical_contract"]
    if (
        set(customer_contract.get("tables", {})) != set(TARGET_TABLE_NAMES)
        or _validate_frozen_customer_contract(customer_contract)
        != FROZEN_TARGET_SCHEMA_SHA256
    ):
        raise CutoverGuardError("revision 126 frozen customer schema is invalid")
    target_profile_contract = resource["target_profile_physical_contract"]
    target_profile_payload = {
        key: value
        for key, value in target_profile_contract.items()
        if key != "contract_sha256"
    }
    if (
        set(target_profile_contract)
        != {"schema_version", "migration_revision", "before", "after", "contract_sha256"}
        or target_profile_contract.get("schema_version") != 1
        or target_profile_contract.get("migration_revision") != revision
        or hashlib.sha256(canonical_json_bytes(target_profile_payload)).hexdigest()
        != target_profile_contract.get("contract_sha256")
    ):
        raise CutoverGuardError("revision 126 frozen target-profile schema is invalid")
    return resource


def _frozen_type(specification: Mapping[str, Any]) -> sa.types.TypeEngine[Any]:
    name = specification["name"]
    length = specification.get("length")
    precision = specification.get("precision")
    scale = specification.get("scale")
    unsigned = specification.get("unsigned") is True
    factories: dict[str, Any] = {
        "BIGINT": lambda: mysql.BIGINT(unsigned=unsigned),
        "BOOLEAN": sa.Boolean,
        "CHAR": lambda: sa.CHAR(length),
        "DATE": sa.Date,
        "DATETIME": sa.DateTime,
        "DECIMAL": lambda: sa.Numeric(precision, scale),
        "INTEGER": lambda: mysql.INTEGER(unsigned=unsigned),
        "INTEGER UNSIGNED": lambda: mysql.INTEGER(unsigned=True),
        "JSON": sa.JSON,
        "LONGTEXT": mysql.LONGTEXT,
        "SMALLINT": lambda: mysql.SMALLINT(unsigned=unsigned),
        "TEXT": sa.Text,
        "TINYINT": lambda: mysql.TINYINT(unsigned=unsigned),
        "VARCHAR": lambda: sa.String(length),
    }
    try:
        return factories[name]()
    except KeyError as exc:
        raise CutoverGuardError(f"unsupported frozen MySQL type: {name}") from exc


def _build_target_metadata(resource: Mapping[str, Any]) -> MetaData:
    metadata = MetaData()
    tables = resource["tables"]
    for table_name in TARGET_TABLE_NAMES:
        signature = tables[table_name]
        columns = []
        for frozen_column in signature["columns"]:
            positional = []
            if frozen_column["computed"] is not None:
                positional.append(
                    sa.Computed(
                        frozen_column["computed"]["expression"],
                        persisted=frozen_column["computed"]["persisted"],
                    )
                )
            columns.append(
                sa.Column(
                    frozen_column["name"],
                    _frozen_type(frozen_column["type"]),
                    *positional,
                    nullable=frozen_column["nullable"],
                    autoincrement=frozen_column["autoincrement"],
                    comment=frozen_column["comment"],
                )
            )
        constraints: list[sa.Constraint] = [
            sa.PrimaryKeyConstraint(
                *signature["primary_key"]["columns"],
                name=signature["primary_key"]["name"],
            )
        ]
        constraints.extend(
            sa.UniqueConstraint(*column_names, name=name)
            for name, column_names in signature["unique_constraints"]
        )
        constraints.extend(
            sa.CheckConstraint(expression, name=name)
            for name, expression, _enforced in signature["checks"]
        )
        sa.Table(
            table_name,
            metadata,
            *columns,
            *constraints,
            comment=signature["table_comment"],
        )

    external_types = {
        "ark_users": mysql.INTEGER(unsigned=True),
        "ark_agent_runs": sa.BigInteger(),
        "ark_job_runs": sa.BigInteger(),
        "ark_sales_target_profiles": sa.BigInteger(),
    }
    external_stubs = tuple(
        sa.Table(name, metadata, sa.Column("id", type_, primary_key=True))
        for name, type_ in external_types.items()
    )
    for table_name in TARGET_TABLE_NAMES:
        signature = tables[table_name]
        table = metadata.tables[table_name]
        for name, unique, column_names in signature["indexes"]:
            sa.Index(name, *(table.c[column] for column in column_names), unique=unique)
        for (
            name,
            local_columns,
            referred_schema,
            referred_table,
            referred_columns,
            ondelete,
            onupdate,
        ) in signature["foreign_keys"]:
            if referred_schema is not None:
                raise CutoverGuardError("revision 126 does not permit cross-schema FKs")
            table.append_constraint(
                sa.ForeignKeyConstraint(
                    local_columns,
                    [
                        f"{referred_table}.{column}"
                        for column in referred_columns
                    ],
                    name=name,
                    ondelete=ondelete,
                    onupdate=onupdate,
                )
            )
    for table_name in TARGET_TABLE_NAMES:
        for foreign_key in metadata.tables[table_name].foreign_keys:
            foreign_key.column
    for stub in external_stubs:
        metadata.remove(stub)
    return metadata


FROZEN_SCHEMA_RESOURCE = _load_frozen_schema_resource()
PHYSICAL_SCHEMA_CONTRACT = FROZEN_SCHEMA_RESOURCE[
    "customer_domain_physical_contract"
]
TARGET_PROFILE_PHYSICAL_CONTRACT = FROZEN_SCHEMA_RESOURCE[
    "target_profile_physical_contract"
]
TARGET_METADATA = _build_target_metadata(PHYSICAL_SCHEMA_CONTRACT)


def _load_cutover_contract() -> Mapping[str, Any]:
    values = context.get_x_argument(as_dictionary=True)
    if set(values) != {"customer_cutover_contract"}:
        raise CutoverGuardError(
            "revision 126 requires only -x customer_cutover_contract=<fixed path>"
        )
    raw_path = values["customer_cutover_contract"]
    if not isinstance(raw_path, str):
        raise CutoverGuardError("customer cutover contract path is required")
    lexical = Path(raw_path)
    root = CUTOVER_EVIDENCE_ROOT.resolve()
    current = lexical
    while current != root and current.is_relative_to(root):
        if current.exists() and current.is_symlink():
            raise CutoverGuardError("customer cutover contract path uses a symlink")
        current = current.parent
    path = lexical.resolve()
    if path.parent != root or not path.name.startswith("migration-contract-"):
        raise CutoverGuardError("customer cutover contract is outside the fixed evidence root")
    try:
        raw = path.read_bytes()
        contract = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise CutoverGuardError("cannot read customer cutover contract") from exc
    if not isinstance(contract, Mapping) or raw != canonical_json_bytes(contract) + b"\n":
        raise CutoverGuardError("customer cutover contract is not canonical JSON")
    if Path(str(contract.get("contract_path"))).resolve() != path:
        raise CutoverGuardError("customer cutover contract path binding is invalid")
    return contract


def _delete_agent_history_closure(
    db: Session, closure: AgentHistoryClosure
) -> None:
    metadata = MetaData()
    for table_name, id_attribute in AGENT_DELETE_ORDER:
        ids = tuple(sorted(getattr(closure, id_attribute)))
        if not ids:
            continue
        table = Table(table_name, metadata, autoload_with=db.connection())
        iterator = iter(ids)
        while chunk := tuple(islice(iterator, AGENT_ID_QUERY_CHUNK_SIZE)):
            result = db.execute(sa.delete(table).where(table.c.id.in_(chunk)))
            if result.rowcount != len(chunk):
                raise CutoverGuardError(
                    f"exact Agent closure delete mismatch for {table_name}"
                )


def _drop_foreign_keys_into_retired(
    db: Session,
    approved_snapshot: Mapping[str, Any],
) -> None:
    validate_incoming_retired_foreign_keys(db, approved_snapshot)
    for foreign_key in approved_snapshot["foreign_keys"]:
        op.drop_constraint(
            foreign_key["constraint_name"],
            foreign_key["owning_table"],
            type_="foreignkey",
        )


def _drop_retired_tables() -> None:
    inspector = sa.inspect(op.get_bind())
    existing = set(inspector.get_table_names())
    for table_name in DROP_ORDER:
        if table_name not in existing:
            if table_name in OPTIONAL_RETIRED_TABLES:
                continue
            raise CutoverGuardError(f"required retired table is missing: {table_name}")
        op.drop_table(table_name)


def _alter_target_profiles(
    db: Session,
    target_profile_policy_backfill: Mapping[str, Any],
) -> None:
    validate_target_profile_policy_backfill_against_live_rows(
        db,
        target_profile_policy_backfill,
    )
    op.add_column(
        "ark_sales_target_profiles",
        sa.Column("policy_version", sa.String(32), nullable=True, comment=TARGET_PROFILE_COLUMNS["policy_version"]),
    )
    op.add_column(
        "ark_sales_target_profiles",
        sa.Column("policy_json", sa.JSON, nullable=True, comment=TARGET_PROFILE_COLUMNS["policy_json"]),
    )
    op.add_column(
        "ark_sales_target_profiles",
        sa.Column("policy_snapshot_hash", CHAR64, nullable=True, comment=TARGET_PROFILE_COLUMNS["policy_snapshot_hash"]),
    )
    op.add_column(
        "ark_sales_target_profiles",
        sa.Column("last_improvement_artifact_id", sa.BigInteger, nullable=True, comment=TARGET_PROFILE_COLUMNS["last_improvement_artifact_id"]),
    )
    op.add_column(
        "ark_sales_target_profiles",
        sa.Column("policy_applied_at", sa.DateTime, nullable=True, comment=TARGET_PROFILE_COLUMNS["policy_applied_at"]),
    )
    for entry in target_profile_policy_backfill["profiles"]:
        expected_snapshot_hash = entry["expected_profile_snapshot_hash"]
        if not isinstance(expected_snapshot_hash, str):
            raise CutoverGuardError("target-profile expected snapshot hash is invalid")
        result = db.execute(
            sa.text(
                "UPDATE ark_sales_target_profiles SET "
                "policy_version=:policy_version, "
                "policy_json=CAST(:policy_json AS JSON), "
                "policy_snapshot_hash=:policy_snapshot_hash, "
                "last_improvement_artifact_id=:last_improvement_artifact_id, "
                "policy_applied_at=:policy_applied_at "
                "WHERE id=:profile_id"
            ),
            {
                "profile_id": entry["profile_id"],
                "policy_version": entry["policy_version"],
                "policy_json": json.dumps(
                    entry["policy_json"],
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                "policy_snapshot_hash": entry["policy_snapshot_hash"],
                "last_improvement_artifact_id": entry[
                    "last_improvement_artifact_id"
                ],
                "policy_applied_at": to_beijing_naive(
                    datetime.fromisoformat(entry["policy_applied_at"])
                ),
            },
        )
        if result.rowcount != 1:
            raise CutoverGuardError(
                f"target-profile policy backfill row mismatch for {entry['profile_id']}"
            )
    op.alter_column("ark_sales_target_profiles", "policy_version", existing_type=sa.String(32), nullable=False, comment=TARGET_PROFILE_COLUMNS["policy_version"], existing_comment=TARGET_PROFILE_COLUMNS["policy_version"])
    op.alter_column("ark_sales_target_profiles", "policy_json", existing_type=sa.JSON(), nullable=False, comment=TARGET_PROFILE_COLUMNS["policy_json"], existing_comment=TARGET_PROFILE_COLUMNS["policy_json"])
    op.alter_column("ark_sales_target_profiles", "policy_snapshot_hash", existing_type=CHAR64, nullable=False, comment=TARGET_PROFILE_COLUMNS["policy_snapshot_hash"], existing_comment=TARGET_PROFILE_COLUMNS["policy_snapshot_hash"])
    op.alter_column("ark_sales_target_profiles", "policy_applied_at", existing_type=sa.DateTime(), nullable=False, comment=TARGET_PROFILE_COLUMNS["policy_applied_at"], existing_comment=TARGET_PROFILE_COLUMNS["policy_applied_at"])
    op.create_index(
        "ix_sales_target_profile_last_improvement_artifact",
        "ark_sales_target_profiles",
        ["last_improvement_artifact_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_sales_target_profile_improvement_artifact",
        "ark_sales_target_profiles",
        "ark_agent_artifacts",
        ["last_improvement_artifact_id"],
        ["id"],
        ondelete="RESTRICT",
        onupdate="RESTRICT",
    )


def _ddl_column(column: sa.Column[Any]) -> sa.Column[Any]:
    positional: list[Any] = []
    if column.computed is not None:
        positional.append(
            sa.Computed(
                str(column.computed.sqltext),
                persisted=column.computed.persisted,
            )
        )
    return sa.Column(
        column.name,
        column.type.copy(),
        *positional,
        nullable=column.nullable,
        autoincrement=column.autoincrement,
        comment=column.comment,
    )


def _non_fk_ddl_constraints(table: sa.Table) -> list[sa.Constraint]:
    constraints: list[sa.Constraint] = [
        sa.PrimaryKeyConstraint(
            *(column.name for column in table.primary_key.columns),
            name=table.primary_key.name,
        )
    ]
    for constraint in tuple(table.constraints):
        if isinstance(constraint, sa.UniqueConstraint):
            constraints.append(
                sa.UniqueConstraint(
                    *(column.name for column in constraint.columns),
                    name=constraint.name,
                )
            )
        elif isinstance(constraint, sa.CheckConstraint):
            constraints.append(
                sa.CheckConstraint(str(constraint.sqltext), name=constraint.name)
            )
    return constraints


def _create_target_tables() -> None:
    for table_name in TARGET_TABLE_NAMES:
        table = TARGET_METADATA.tables[table_name]
        op.create_table(
            table_name,
            *(_ddl_column(column) for column in table.c),
            *_non_fk_ddl_constraints(table),
            comment=table.comment,
        )
    for table_name in TARGET_TABLE_NAMES:
        table = TARGET_METADATA.tables[table_name]
        for index in sorted(table.indexes, key=lambda item: item.name or ""):
            op.create_index(
                index.name,
                table_name,
                [column.name for column in index.columns],
                unique=index.unique,
            )
    for table_name in TARGET_TABLE_NAMES:
        table = TARGET_METADATA.tables[table_name]
        foreign_keys = sorted(
            (
                constraint
                for constraint in table.constraints
                if isinstance(constraint, sa.ForeignKeyConstraint)
            ),
            key=lambda item: item.name or "",
        )
        for foreign_key in foreign_keys:
            elements = tuple(foreign_key.elements)
            op.create_foreign_key(
                foreign_key.name,
                table_name,
                elements[0].column.table.name,
                [element.parent.name for element in elements],
                [element.column.name for element in elements],
                ondelete=foreign_key.ondelete,
                onupdate=foreign_key.onupdate,
            )


def _verify_frozen_customer_table_state(db: Session) -> None:
    connection = db.connection()
    inspector = sa.inspect(connection)
    missing = [
        table_name
        for table_name in TARGET_TABLE_NAMES
        if not inspector.has_table(table_name)
    ]
    if missing:
        raise CutoverGuardError(
            "revision 126 customer tables are missing: " + ", ".join(missing)
        )
    retired_only = set(RETIRED_OR_REBUILT_TABLES) - set(TARGET_TABLE_NAMES)
    remaining = sorted(
        table_name
        for table_name in retired_only
        if inspector.has_table(table_name)
    )
    if remaining:
        raise CutoverGuardError(
            "revision 126 retired tables still exist: " + ", ".join(remaining)
        )
    for table_name in TARGET_TABLE_NAMES:
        compare_physical_schema_signature(
            PHYSICAL_SCHEMA_CONTRACT["tables"][table_name],
            _reflected_physical_schema_signature(
                inspector,
                table_name,
                connection=connection,
            ),
            table_name,
        )


def _publish_atomic_no_overwrite(path: Path, document: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(
        f".{path.name}.{os.urandom(8).hex()}.tmp"
    )
    descriptor = None
    try:
        descriptor = os.open(
            temporary_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = None
            stream.write(canonical_json_bytes(document) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary_path, path)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass


def _write_ddl_proof(contract: Mapping[str, Any], started_at: datetime) -> None:
    root = CUTOVER_EVIDENCE_ROOT.resolve()
    ddl_proof_path = (root / str(contract["ddl_proof_path"])).resolve()
    expected_name = f"migration-ddl-proof-{contract['nonce']}.json"
    if ddl_proof_path.parent != root or ddl_proof_path.name != expected_name:
        raise CutoverGuardError("migration DDL proof path is not fixed")
    completed_at = beijing_now_aware()
    proof = {
        field: contract[field]
        for field in (
            "inventory_sha256",
            "preflight_report_sha256",
            "suppression_manifest_sha256",
            "writer_manifest_sha256",
            "writer_privilege_revocation_artifact_sha256",
            "approved_marker_sha256",
            "maintenance_fence_artifact_sha256",
            "instance_inventory_artifact_sha256",
            "physical_schema_contract_sha256",
            "target_profile_physical_contract_sha256",
            "target_profile_policy_backfill_sha256",
            "nonce",
            "contract_sha256",
            "contract_path",
            "ddl_proof_path",
            "ddl_proof_binding_sha256",
        )
    }
    proof.update(
        {
            "migration_revision": revision,
            "schema_signature_sha256": contract["physical_schema_contract_sha256"],
            "started_at": started_at.isoformat(timespec="seconds"),
            "completed_at": completed_at.isoformat(timespec="seconds"),
            "status": "ddl_verified",
        }
    )
    proof["ddl_proof_sha256"] = hashlib.sha256(
        canonical_json_bytes(proof)
    ).hexdigest()
    try:
        _publish_atomic_no_overwrite(ddl_proof_path, proof)
    except OSError as exc:
        raise CutoverGuardError(
            f"migration DDL proof publish failed: {ddl_proof_path}; "
            "keep all writers stopped"
        ) from exc


def upgrade() -> None:
    started_at = beijing_now_aware()
    contract = _load_cutover_contract()
    _validate_frozen_customer_contract(PHYSICAL_SCHEMA_CONTRACT)
    if contract.get("target_profile_physical_contract_sha256") != (
        TARGET_PROFILE_PHYSICAL_CONTRACT["contract_sha256"]
    ):
        raise CutoverGuardError(
            "bound target-profile physical contract does not match revision 126"
        )
    bound_evidence = load_bound_customer_cutover_evidence(
        contract,
        physical_schema_validator=_validate_frozen_customer_contract,
    )
    bound_physical_contract = bound_evidence["physical_schema_contract"]
    target_profile_policy_backfill = bound_evidence[
        "target_profile_policy_backfill"
    ]
    validate_target_profile_policy_backfill_artifact(
        target_profile_policy_backfill
    )
    if canonical_json_bytes(bound_physical_contract) != canonical_json_bytes(
        PHYSICAL_SCHEMA_CONTRACT
    ):
        raise CutoverGuardError(
            "bound physical schema contract does not match revision 126 frozen DDL"
        )
    preflight_report = bound_evidence["preflight_report"]
    approved_closure = AgentHistoryClosure.from_dict(
        preflight_report["agent_history_closure"]
    )
    unrelated_agent_snapshot = AgentPreservationSnapshot.from_dict(
        preflight_report["unrelated_agent_snapshot"]
    )
    writer_privilege_evidence, _, _ = load_writer_privilege_revocation_evidence(
        bound_evidence["writer_manifest"]
    )
    referenced_improvement_artifacts = {
        entry["last_improvement_artifact_id"]
        for entry in target_profile_policy_backfill["profiles"]
        if entry["last_improvement_artifact_id"] is not None
    }
    if referenced_improvement_artifacts & approved_closure.artifact_ids:
        raise CutoverGuardError(
            "target-profile improvement Artifact belongs to the deletion closure"
        )
    bind = op.get_bind()
    db = Session(bind=bind)
    bootstrap_migration_fence(
        db,
        contract,
        physical_schema_validator=_validate_frozen_customer_contract,
    )
    inventory = migration_preflight(
        db,
        contract,
        target_profile_physical_contract=TARGET_PROFILE_PHYSICAL_CONTRACT[
            "before"
        ],
        target_profile_policy_backfill=target_profile_policy_backfill,
        physical_schema_validator=_validate_frozen_customer_contract,
    )
    closure = resolve_agent_history_closure(db, inventory)
    if closure != approved_closure:
        raise CutoverGuardError("live Agent deletion closure changed after approval")
    before_ddl_snapshot = snapshot_unrelated_agent_rows(db, closure)
    verify_unrelated_unchanged(
        unrelated_agent_snapshot,
        before_ddl_snapshot,
    )
    validate_mysql_writer_privilege_gate(
        db,
        writer_privilege_evidence,
        now=beijing_now_aware(),
    )
    _drop_foreign_keys_into_retired(
        db,
        preflight_report["incoming_retired_foreign_keys"],
    )
    _delete_agent_history_closure(db, closure)
    verify_agent_history_removed(db, closure)
    after_delete_snapshot = snapshot_unrelated_agent_rows(db, closure)
    verify_unrelated_unchanged(
        unrelated_agent_snapshot,
        after_delete_snapshot,
    )
    _drop_retired_tables()
    _alter_target_profiles(db, target_profile_policy_backfill)
    _create_target_tables()
    _verify_frozen_customer_table_state(db)
    verify_target_profile_post_state(
        db,
        TARGET_PROFILE_PHYSICAL_CONTRACT["after"],
        target_profile_policy_backfill,
    )
    before_receipt_snapshot = snapshot_unrelated_agent_rows(db, closure)
    verify_unrelated_unchanged(
        unrelated_agent_snapshot,
        before_receipt_snapshot,
    )
    _write_ddl_proof(contract, started_at)


def downgrade() -> None:
    raise RuntimeError("destructive customer-domain restoration is unsupported")
