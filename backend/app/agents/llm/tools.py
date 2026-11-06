"""Approved tools of the Objective III agents (docs/08 §5, D-50) — also served by the MCP server `retailpilot-tools`.

READ tools return facts from PostgreSQL through existing models and deterministic tools; DRAFT_WRITE tools only
create `agent_draft` rows that a human decides through the existing workflows. There is NO tool that approves,
submits, dispatches, receives, changes business rules or changes stock (rule 8): those operations do not exist
here, so an agent cannot perform them whatever it is asked.

Scoping (rule 10) is enforced inside every tool from `ToolContext` (the calling user's role and store), never from
model arguments: a Store Supervisor's tool calls only see their own store; another store appears as name + qty.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import desc, func, or_, select, text
from sqlalchemy.orm import Session

from app.agents.llm.framework import ToolContext, ToolError, ToolSpec
from app.agents.registry import BY_KEY
from app.domain.models.agents import AgentDraft, PolicyDocument
from app.domain.models.enums import DraftStatus, RecStatus
from app.domain.models.inventory import InventoryMovement, InventoryPosition
from app.domain.models.master import Product, Store
from app.domain.models.observability import NIGHTLY_AGENT, AgentRun
from app.domain.models.planning import Recommendation
from app.domain.models.transfers import BusinessRule, TransferOrder
from app.services.agent_decision_service import record_decision
from app.services.explanation_service import PRIVATE_FIELDS


class Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- helpers ---------------------------------------------------------------------------------------------------------


def latest_nightly_run_id(session: Session) -> UUID | None:
    run_id: UUID | None = session.scalar(
        select(AgentRun.run_id)
        .where(AgentRun.agent_name == NIGHTLY_AGENT, AgentRun.status.in_(["SUCCESS", "PARTIAL"]))
        .order_by(desc(AgentRun.started_at))
        .limit(1)
    )
    return run_id


def _scope_run(ctx: ToolContext) -> UUID | None:
    if ctx.scope_run_id is None:
        ctx.scope_run_id = latest_nightly_run_id(ctx.session)
    return ctx.scope_run_id


def _uuid(value: str, field: str) -> UUID:
    try:
        return UUID(str(value))
    except ValueError as exc:
        raise ToolError(f"{field} must be an id returned by a previous tool") from exc


def _store_names(ctx: ToolContext) -> dict[UUID, str]:
    if "stores" not in ctx.cache:
        ctx.cache["stores"] = dict(ctx.session.execute(select(Store.store_id, Store.name)).all())
    return ctx.cache["stores"]  # type: ignore[no-any-return]


def _rec_visible(ctx: ToolContext, rec: Recommendation) -> bool:
    if ctx.is_admin or rec.store_id == ctx.store_id:
        return True
    donor = ctx.session.scalar(
        select(TransferOrder.from_store_id).where(TransferOrder.source_rec_id == rec.rec_id)
    )
    return donor == ctx.store_id  # a donor's supervisor may open a transfer it donates to (D-32)


def _scoped_evidence(ctx: ToolContext, rec: Recommendation) -> dict[str, Any]:
    ev = dict(rec.evidence or {})
    if ctx.is_admin:
        return ev
    donor = (ev.get("donor") or {}).get("store", {}).get("store_id")
    if str(donor) == str(ctx.store_id):
        return ev
    return {k: v for k, v in ev.items() if k not in PRIVATE_FIELDS}


_WORD = re.compile(r"[a-z0-9]{3,}")
_STOP = {
    "the",
    "and",
    "why",
    "are",
    "what",
    "how",
    "did",
    "for",
    "this",
    "that",
    "with",
    "our",
    "week",
    "store",
    "ordering",
    "order",
    "many",
    "much",
    "was",
    "were",
    "today",
    "about",
    "from",
    "does",
    "have",
    "has",
}


def _terms(query: str) -> list[str]:
    return [w for w in _WORD.findall(query.lower()) if w not in _STOP][:6]


# --- READ tools ------------------------------------------------------------------------------------------------------


class SearchArgs(Args):
    query: str = Field(min_length=2, max_length=200, description="Words to search for, e.g. a product name")
    limit: int = Field(5, ge=1, le=8)


def search_records(ctx: ToolContext, a: SearchArgs) -> dict[str, Any]:
    run_id = _scope_run(ctx)
    terms = _terms(a.query)
    if not terms:
        return {"items": [], "note": "no searchable words"}
    stmt = (
        select(Recommendation, Store.name, Product.name, Product.sku, Product.category)
        .join(Store, Store.store_id == Recommendation.store_id)
        .join(Product, Product.product_id == Recommendation.product_id)
        .where(or_(*[Product.name.ilike(f"%{t}%") | Product.category.ilike(f"%{t}%") for t in terms]))
        .order_by(desc(Recommendation.created_at))
        .limit(a.limit)
    )
    if run_id is not None:
        stmt = stmt.where(Recommendation.run_id == run_id)
    if not ctx.is_admin:
        stmt = stmt.where(Recommendation.store_id == ctx.store_id)
    items = [
        {
            "rec_id": rec.rec_id,
            "store": store_name,
            "product": product_name,
            "sku": sku,
            "rec_type": rec.rec_type,
            "qty": rec.qty,
            "status": rec.status,
            "explanation": (rec.explanation or "")[:300],
        }
        for rec, store_name, product_name, sku, _cat in ctx.session.execute(stmt).all()
    ]
    return {"items": items, "count": len(items)}


def search_policies(ctx: ToolContext, a: SearchArgs) -> dict[str, Any]:
    q = func.websearch_to_tsquery("english", a.query)
    rows = ctx.session.execute(
        select(PolicyDocument, func.ts_rank(PolicyDocument.search_tsv, q).label("rank"))
        .where(PolicyDocument.search_tsv.op("@@")(q))
        .order_by(desc("rank"))
        .limit(a.limit)
    ).all()
    if not rows:  # websearch syntax is strict (all words); fall back to any word
        terms = _terms(a.query)
        if terms:
            q2 = func.to_tsquery("english", " | ".join(terms))
            rows = ctx.session.execute(
                select(PolicyDocument, func.ts_rank(PolicyDocument.search_tsv, q2).label("rank"))
                .where(PolicyDocument.search_tsv.op("@@")(q2))
                .order_by(desc("rank"))
                .limit(a.limit)
            ).all()
    return {
        "items": [
            {"section_id": d.section_id, "document": d.title, "section": d.heading, "text": d.body[:700]}
            for d, _rank in rows
        ]
    }


class RecArgs(Args):
    rec_id: str = Field(description="rec_id returned by search_records or another tool")


def get_recommendation(ctx: ToolContext, a: RecArgs) -> dict[str, Any]:
    rec = ctx.session.get(Recommendation, _uuid(a.rec_id, "rec_id"))
    if rec is None or not _rec_visible(ctx, rec):
        raise ToolError("recommendation not found")  # same answer for other stores: no existence leak
    product = ctx.session.get(Product, rec.product_id)
    ev = rec.evidence or {}
    allowed = {rec.qty}
    for k in ("need_qty", "destination_shortage", "transfer_qty", "po_remainder_qty", "qty"):
        if isinstance(ev.get(k), int):
            allowed.add(int(ev[k]))
    ctx.allowed_qty.setdefault(str(rec.rec_id), set()).update(q for q in allowed if q >= 0)
    return {
        "rec_id": rec.rec_id,
        "store": _store_names(ctx).get(rec.store_id),
        "store_id": rec.store_id if ctx.is_admin else None,
        "product": product.name if product else None,
        "product_id": rec.product_id,
        "rec_type": rec.rec_type,
        "status": rec.status,
        "priority": rec.priority,
        "qty": rec.qty,
        "reason": rec.reason,
        "explanation": rec.explanation,
        "run_id": rec.run_id,
        "created_at": rec.created_at,
    }


def get_evidence(ctx: ToolContext, a: RecArgs) -> dict[str, Any]:
    rec = ctx.session.get(Recommendation, _uuid(a.rec_id, "rec_id"))
    if rec is None or not _rec_visible(ctx, rec):
        raise ToolError("recommendation not found")
    return {"rec_id": rec.rec_id, "evidence": _scoped_evidence(ctx, rec)}


class PositionArgs(Args):
    product: str = Field(min_length=2, max_length=100, description="Product name or SKU (partial match)")
    store_id: str | None = Field(None, description="Super Admin only; supervisors always get their own store")


def get_inventory_position(ctx: ToolContext, a: PositionArgs) -> dict[str, Any]:
    stmt = (
        select(InventoryPosition, Product.name, Product.sku)
        .join(Product, Product.product_id == InventoryPosition.product_id)
        .where(Product.name.ilike(f"%{a.product}%") | Product.sku.ilike(f"%{a.product}%"))
        .limit(12)
    )
    if not ctx.is_admin:
        stmt = stmt.where(InventoryPosition.store_id == ctx.store_id)
    elif a.store_id:
        stmt = stmt.where(InventoryPosition.store_id == _uuid(a.store_id, "store_id"))
    names = _store_names(ctx)
    rows = [
        {
            "store": names.get(p.store_id),
            "store_id": p.store_id,
            "product": name,
            "product_id": p.product_id,
            "sku": sku,
            "shelf": p.shelf_qty,
            "backroom": p.backroom_qty,
            "incoming": p.incoming,
            "reserved": p.reserved,
            "available": p.available,
        }
        for p, name, sku in ctx.session.execute(stmt).all()
    ]
    return {"positions": rows}


class RulesArgs(Args):
    keys: list[str] | None = Field(None, description="Rule keys; omit for all global rules")


def get_business_rules(ctx: ToolContext, a: RulesArgs) -> dict[str, Any]:
    stmt = select(BusinessRule.rule_key, BusinessRule.value).where(BusinessRule.scope_store_id.is_(None))
    if a.keys:
        stmt = stmt.where(BusinessRule.rule_key.in_(a.keys))
    rules = {k: v for k, v in ctx.session.execute(stmt).all()}
    return {"rules": rules, "section_id": "business_rules"}


class TransfersArgs(Args):
    days: int = Field(7, ge=1, le=31)
    store: str | None = Field(None, description="Store name (Super Admin only)")


def list_transfers(ctx: ToolContext, a: TransfersArgs) -> dict[str, Any]:
    since = datetime.now(UTC) - timedelta(days=a.days)
    stmt = (
        select(TransferOrder, Product.name)
        .join(Product, Product.product_id == TransferOrder.product_id)
        .where(TransferOrder.created_at >= since)
        .order_by(desc(TransferOrder.created_at))
        .limit(25)
    )
    names = _store_names(ctx)
    if not ctx.is_admin:
        stmt = stmt.where(
            (TransferOrder.from_store_id == ctx.store_id) | (TransferOrder.to_store_id == ctx.store_id)
        )
    elif a.store:
        ids = [sid for sid, n in names.items() if a.store.lower() in n.lower()]
        stmt = stmt.where(TransferOrder.from_store_id.in_(ids) | TransferOrder.to_store_id.in_(ids))
    return {
        "transfers": [
            {
                "transfer_id": t.transfer_id,
                "from_store": names.get(t.from_store_id),
                "to_store": names.get(t.to_store_id),
                "product": pname,
                "qty": t.qty,
                "status": t.status,
                "created_at": t.created_at,
                "rec_id": t.source_rec_id,
            }
            for t, pname in ctx.session.execute(stmt).all()
        ]
    }


class TransferOptionsArgs(Args):
    rec_id: str


def get_transfer_options(ctx: ToolContext, a: TransferOptionsArgs) -> dict[str, Any]:
    """Requirement, available and surplus of every store for the recommendation's product — computed with the
    deterministic RequirementCalculator on the nightly run's forecasts (rule 1). Donor protection: only surplus>0."""
    from app.agents.planning_inputs import PlanningInputs

    rec = ctx.session.get(Recommendation, _uuid(a.rec_id, "rec_id"))
    if rec is None or not _rec_visible(ctx, rec):
        raise ToolError("recommendation not found")
    run_id = rec.run_id
    key = f"planning:{run_id}"
    if key not in ctx.cache:
        store_ids = list(ctx.session.scalars(select(Store.store_id)))
        ctx.cache[key] = PlanningInputs.load(ctx.session, run_id, store_ids)
    inputs = ctx.cache[key]
    from app.tools.requirement import RequirementCalculator as RC  # noqa: N817

    names = _store_names(ctx)
    need_state = inputs.state(rec.store_id, rec.product_id)
    need = max(0, need_state.requirement - need_state.available)
    donors = []
    for sid in names:
        if sid == rec.store_id:
            continue
        st = inputs.state(sid, rec.product_id)
        surplus = RC.surplus(st.available, st.requirement)
        if surplus > 0 and not inputs.is_low_confidence(sid, rec.product_id):
            donors.append({"store_id": sid, "store": names[sid], "surplus": surplus})
    allowed = (
        {need, rec.qty}
        | {min(need, d["surplus"]) for d in donors}
        | {max(0, need - d["surplus"]) for d in donors}
    )
    ctx.allowed_qty.setdefault(str(rec.rec_id), set()).update(q for q in allowed if q >= 0)
    ctx.cache.setdefault("donor_surplus", {})[str(rec.rec_id)] = {
        str(d["store_id"]): d["surplus"] for d in donors
    }
    return {
        "rec_id": rec.rec_id,
        "need_qty": need,
        "own_requirement": need_state.requirement,
        "available": need_state.available,
        "low_confidence": inputs.is_low_confidence(rec.store_id, rec.product_id),
        "donors": donors
        if ctx.is_admin
        else [{"store": d["store"], "surplus": d["surplus"]} for d in donors],
    }


class IngestionArgs(Args):
    max_items: int = Field(20, ge=1, le=50)


def get_ingestion_report(ctx: ToolContext, a: IngestionArgs) -> dict[str, Any]:
    """SD-02 signals for the latest POS day: stale SKUs (stock held, no sale > stale_days), reconciliation
    adjustments (snapshot vs ledger mismatches) and zero-stock snapshots with sales (anomalies)."""
    latest = ctx.session.scalar(text("SELECT max(snapshot_date) FROM inventory_daily_snapshot"))
    if latest is None:
        return {"date": None, "issues": [], "note": "no POS data loaded"}
    stale_days = int(
        ctx.session.scalar(
            select(BusinessRule.value).where(
                BusinessRule.rule_key == "stale_days", BusinessRule.scope_store_id.is_(None)
            )
        )
        or 3
    )
    names = _store_names(ctx)
    store_filter = "" if ctx.is_admin else "AND p.store_id = :store"
    params: dict[str, Any] = {"day": latest, "stale": stale_days, "lim": a.max_items}
    if not ctx.is_admin:
        params["store"] = ctx.store_id
    stale = ctx.session.execute(
        text(
            f"""
            SELECT p.store_id, p.product_id, pr.name, max(sl.txn_date) AS last_sale,
                   p.shelf_qty + p.backroom_qty AS on_hand
            FROM inventory_position p
            JOIN product pr ON pr.product_id = p.product_id
            LEFT JOIN sales_line sl ON sl.store_id = p.store_id AND sl.product_id = p.product_id
                 AND sl.txn_date > :day - 60
            WHERE p.shelf_qty + p.backroom_qty > 0 {store_filter}
            GROUP BY p.store_id, p.product_id, pr.name, p.shelf_qty, p.backroom_qty
            HAVING max(sl.txn_date) IS NOT NULL AND :day - max(sl.txn_date) > :stale
            ORDER BY :day - max(sl.txn_date) DESC LIMIT :lim
            """
        ),
        params,
    ).all()
    adj_stmt = (
        select(
            InventoryMovement.store_id,
            InventoryMovement.product_id,
            InventoryMovement.qty,
            InventoryMovement.business_date,
            InventoryMovement.reason,
            Product.name,
        )
        .join(Product, Product.product_id == InventoryMovement.product_id)
        .where(
            InventoryMovement.movement_type == "ADJUSTMENT",
            InventoryMovement.business_date >= latest - timedelta(days=14),
        )
        .order_by(desc(InventoryMovement.business_date))
        .limit(a.max_items)
    )
    if not ctx.is_admin:
        adj_stmt = adj_stmt.where(InventoryMovement.store_id == ctx.store_id)
    issues: list[dict[str, Any]] = []
    for sid, pid, pname, last_sale, on_hand in stale:
        issues.append(
            {
                "evidence_id": f"stale:{sid}:{pid}",
                "signal": "STALE_SKU",
                "store": names.get(sid),
                "store_id": sid,
                "product": pname,
                "product_id": pid,
                "days_since_last_sale": (latest - last_sale).days,
                "on_hand": on_hand,
            }
        )
    for sid, pid, qty, day, reason, pname in ctx.session.execute(adj_stmt).all():
        issues.append(
            {
                "evidence_id": f"adjustment:{sid}:{pid}:{day}",
                "signal": "SNAPSHOT_MISMATCH",
                "store": names.get(sid),
                "store_id": sid,
                "product": pname,
                "product_id": pid,
                "adjustment_qty": qty,
                "date": day,
                "reason": reason,
            }
        )
    ctx.cache["ingestion_evidence"] = {i["evidence_id"]: i for i in issues}
    return {"date": latest, "stale_days_rule": stale_days, "issues": issues, "count": len(issues)}


class RunLogArgs(Args):
    run_id: str | None = Field(None, description="Root run id; omit for the latest nightly run")


def get_run_log(ctx: ToolContext, a: RunLogArgs) -> dict[str, Any]:
    if not ctx.is_admin:
        raise ToolError("run logs are Super Admin only")
    root_id = (
        _uuid(a.run_id, "run_id")
        if a.run_id
        else (ctx.cache.get("root_run_id") or latest_nightly_run_id(ctx.session))
    )
    if root_id is None:
        return {"run": None, "stages": []}
    root = ctx.session.get(AgentRun, root_id)
    if root is None:
        raise ToolError("run not found")
    children = ctx.session.scalars(
        select(AgentRun).where(AgentRun.parent_run_id == root_id).order_by(AgentRun.started_at)
    ).all()
    return {
        "run_id": root.run_id,
        "status": root.status,
        "run_date": root.run_date,
        "stages": [
            {
                "agent_key": c.agent_key,
                "status": c.status,
                "error": (c.error or "")[:200] or None,
                "critical": bool(c.agent_key and BY_KEY.get(c.agent_key) and BY_KEY[c.agent_key].critical),
                "retries": c.retries,
                # a coordinator retry is a second child run of the same agent in this run
                "coordinator_retried": sum(1 for x in children if x.agent_key == c.agent_key) > 1,
            }
            for c in children
        ],
    }


def get_exception_summary(ctx: ToolContext, a: RunLogArgs) -> dict[str, Any]:
    if not ctx.is_admin:
        raise ToolError("Super Admin only")
    log = get_run_log(ctx, a)
    run_id = log.get("run_id")
    needs_review = 0
    if run_id:
        needs_review = int(
            ctx.session.scalar(
                select(func.count())
                .select_from(Recommendation)
                .where(Recommendation.run_id == run_id, Recommendation.status == RecStatus.NEEDS_REVIEW.value)
            )
            or 0
        )
    failed = [s for s in log["stages"] if s["status"] == "FAILED"]
    return {
        "run_id": run_id,
        "run_status": log.get("status"),
        "failed_stages": failed,
        "skipped_stages": [s["agent_key"] for s in log["stages"] if str(s["status"]).startswith("SKIPPED")],
        "needs_review_recommendations": needs_review,
    }


# --- DRAFT_WRITE tools -------------------------------------------------------------------------------------------


class DraftArgs(Args):
    rec_id: str
    draft_type: Literal["TRANSFER_DRAFT", "PO_DRAFT"]
    qty: int = Field(ge=1)
    from_store_id: str | None = Field(
        None, description="Donor store id for a TRANSFER_DRAFT (from get_transfer_options)"
    )
    rationale: str = Field(min_length=10, max_length=600)


def create_draft_recommendation(ctx: ToolContext, a: DraftArgs) -> dict[str, Any]:
    """Create a DRAFT proposal for a human to decide — never approves, submits or changes stock."""
    rec = ctx.session.get(Recommendation, _uuid(a.rec_id, "rec_id"))
    if rec is None or not _rec_visible(ctx, rec):
        raise ToolError("recommendation not found")
    allowed = ctx.allowed_qty.get(str(rec.rec_id), set())
    if a.qty not in allowed:
        raise ToolError(
            f"qty {a.qty} was not returned by a tool for this recommendation; allowed: {sorted(allowed)}"
        )
    if a.draft_type == "TRANSFER_DRAFT":
        if not a.from_store_id:
            raise ToolError("a TRANSFER_DRAFT needs from_store_id")
        surplus = ctx.cache.get("donor_surplus", {}).get(str(rec.rec_id), {}).get(a.from_store_id)
        if surplus is None:
            raise ToolError("from_store_id is not a donor returned by get_transfer_options")
        if a.qty > surplus:  # rule 3: never take a donor below its own requirement
            raise ToolError(f"donor protection: qty {a.qty} exceeds the donor's surplus {surplus}")
    draft = AgentDraft(
        draft_id=uuid.uuid4(),
        run_id=ctx.root_run_id,
        agent_key="replenishment_action",
        draft_type=a.draft_type,
        mode=ctx.mode,
        store_id=rec.store_id,
        product_id=rec.product_id,
        source_rec_id=rec.rec_id,
        qty=a.qty,
        payload={"from_store_id": a.from_store_id, "rationale": a.rationale},
        status=DraftStatus.DRAFT.value,
    )
    ctx.session.add(draft)
    ctx.session.flush()
    record_decision(
        ctx.session,
        run_id=ctx.root_run_id,
        agent_key="replenishment_action",
        decision_type="DRAFT_CREATED",
        mode=ctx.mode,
        outcome="PENDING",
        store_id=rec.store_id,
        product_id=rec.product_id,
        rec_id=rec.rec_id,
        draft_id=draft.draft_id,
        summary=f"Draft {'transfer' if a.draft_type == 'TRANSFER_DRAFT' else 'order'} of {a.qty} for review",
        evidence_ref={"rationale": a.rationale, "from_store_id": a.from_store_id},
    )
    return {
        "draft_id": draft.draft_id,
        "status": "DRAFT",
        "next": "A supervisor decides it on the recommendation",
    }


class DataReviewArgs(Args):
    category: Literal["STALE_SKU", "SNAPSHOT_MISMATCH", "SALES_ANOMALY", "MISSING_DATA", "OTHER"]
    summary: str = Field(min_length=10, max_length=400)
    severity: Literal["LOW", "MEDIUM", "HIGH"]
    evidence_ids: list[str] = Field(min_length=1, max_length=10)


def create_data_review_item(ctx: ToolContext, a: DataReviewArgs) -> dict[str, Any]:
    known = ctx.cache.get("ingestion_evidence", {})
    unknown = [e for e in a.evidence_ids if e not in known]
    if unknown:
        raise ToolError(f"evidence ids not returned by get_ingestion_report: {unknown[:3]}")
    first = known[a.evidence_ids[0]]
    draft = AgentDraft(
        draft_id=uuid.uuid4(),
        run_id=ctx.root_run_id,
        agent_key="data_quality",
        draft_type="DATA_REVIEW_ITEM",
        mode=ctx.mode,
        store_id=first.get("store_id"),
        product_id=first.get("product_id"),
        payload={
            "category": a.category,
            "summary": a.summary,
            "severity": a.severity,
            "evidence_ids": a.evidence_ids,
        },
    )
    ctx.session.add(draft)
    ctx.session.flush()
    record_decision(
        ctx.session,
        run_id=ctx.root_run_id,
        agent_key="data_quality",
        decision_type="NEEDS_REVIEW_RAISED",
        mode=ctx.mode,
        outcome="PENDING",
        store_id=first.get("store_id"),
        product_id=first.get("product_id"),
        draft_id=draft.draft_id,
        summary=f"[{a.severity}] {a.category}: {a.summary}",
        evidence_ref={"evidence_ids": a.evidence_ids},
    )
    return {"draft_id": draft.draft_id, "status": "DRAFT"}


TOOLS: dict[str, ToolSpec] = {
    t.name: t
    for t in [
        ToolSpec(
            "search_records",
            "Search this run's recommendations by product or category words.",
            SearchArgs,
            "READ",
            search_records,
        ),
        ToolSpec(
            "search_policies",
            "Full-text search of SOP and policy documents; returns cited sections.",
            SearchArgs,
            "READ",
            search_policies,
        ),
        ToolSpec(
            "get_recommendation",
            "One recommendation by rec_id (store-scoped).",
            RecArgs,
            "READ",
            get_recommendation,
        ),
        ToolSpec(
            "get_evidence",
            "The deterministic evidence behind a recommendation (store-scoped).",
            RecArgs,
            "READ",
            get_evidence,
        ),
        ToolSpec(
            "get_inventory_position",
            "Shelf, backroom, incoming, reserved and available stock of a product.",
            PositionArgs,
            "READ",
            get_inventory_position,
        ),
        ToolSpec(
            "get_business_rules",
            "Global business rules (thresholds, costs, windows).",
            RulesArgs,
            "READ",
            get_business_rules,
        ),
        ToolSpec(
            "list_transfers", "Recent stock transfers (store-scoped).", TransfersArgs, "READ", list_transfers
        ),
        ToolSpec(
            "get_transfer_options",
            "Need, requirement and donor surplus per store for a recommendation's product (deterministic).",
            TransferOptionsArgs,
            "READ",
            get_transfer_options,
        ),
        ToolSpec(
            "get_ingestion_report",
            "Stale SKUs, snapshot mismatches and anomalies of the latest POS day.",
            IngestionArgs,
            "READ",
            get_ingestion_report,
        ),
        ToolSpec(
            "get_run_log", "Stages, statuses and errors of a pipeline run.", RunLogArgs, "READ", get_run_log
        ),
        ToolSpec(
            "get_exception_summary",
            "Failed / skipped stages and NEEDS_REVIEW counts of a run.",
            RunLogArgs,
            "READ",
            get_exception_summary,
        ),
        ToolSpec(
            "create_draft_recommendation",
            "Create a DRAFT transfer/order proposal for a human to decide. Cannot approve or submit.",
            DraftArgs,
            "DRAFT_WRITE",
            create_draft_recommendation,
        ),
        ToolSpec(
            "create_data_review_item",
            "Create a DRAFT data-review item for the Super Admin.",
            DataReviewArgs,
            "DRAFT_WRITE",
            create_data_review_item,
        ),
    ]
}


def tools_for(agent_key: str) -> list[ToolSpec]:
    """The explicit allow-list of an agent (registry read_tools + draft_tools)."""
    spec = BY_KEY[agent_key]
    return [TOOLS[n] for n in (*spec.read_tools, *spec.draft_tools) if n in TOOLS]
