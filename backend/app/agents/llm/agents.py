"""The five Objective III agents (docs/08 §3, D-50) — one per pattern.

Each agent: versioned system prompt, explicit tool allow-list (registry), Pydantic output contract validated by the
tool loop (invalid → one retry → fail safe), code checks on the output, and a deterministic BASELINE that is both
the fail-safe when no LLM is available (no key, template provider, global LLM switch off, model error) and the
comparison point of the evaluation (docs/notes/agent-pattern-comparison.md).
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.agents.base import AgentResult, BaseAgent, RunContext
from app.agents.llm.chat import ChatLLM, GroqChatClient
from app.agents.llm.framework import Limits, LoopResult, ToolContext, ToolError, ToolLoopAgent, remember
from app.agents.llm.tools import (
    DataReviewArgs,
    DraftArgs,
    IngestionArgs,
    RecArgs,
    RunLogArgs,
    SearchArgs,
    TransferOptionsArgs,
    create_data_review_item,
    create_draft_recommendation,
    get_evidence,
    get_exception_summary,
    get_ingestion_report,
    get_recommendation,
    get_run_log,
    get_transfer_options,
    search_policies,
    search_records,
    tools_for,
)
from app.agents.registry import BY_KEY
from app.core.config import Settings, get_settings
from app.domain.models.agents import RecommendationReview
from app.domain.models.enums import RecStatus
from app.domain.models.planning import Recommendation
from app.services.agent_decision_service import record_decision
from app.services.explanation_service import PRIVATE_FIELDS, fact_numbers, is_grounded, llm_facts
from app.services.llm_client import GroqClient, JsonLLM, LLMError

PROMPTS = Path(__file__).parent / "prompts"


def load_prompt(version: str) -> str:
    return (PROMPTS / f"{version}.md").read_text(encoding="utf-8")


def limits_for(agent_key: str) -> Limits:
    s = BY_KEY[agent_key].stopping
    return Limits(
        max_tool_calls=s.max_tool_calls or 6,
        max_tokens=s.max_tokens or 12_000,
        timeout_s=float(s.timeout_s or 45),
    )


def make_chat_llm(settings: Settings | None = None) -> ChatLLM | None:
    """The live model, or None when LLM agents must use their deterministic baseline."""
    settings = settings or get_settings()
    if settings.llm_provider == "template" or settings.groq_api_key is None:
        return None
    return GroqChatClient(settings)


def make_json_llm(settings: Settings | None = None) -> JsonLLM | None:
    settings = settings or get_settings()
    if settings.llm_provider == "template" or settings.groq_api_key is None:
        return None
    return GroqClient(settings)


# =====================================================================================================================
# 1. Ask RetailPilot — research / retrieval
# =====================================================================================================================


class Citation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_type: Literal["RECOMMENDATION", "EVIDENCE", "BUSINESS_RULE", "POLICY", "TRANSFER", "INVENTORY"]
    source_id: str = Field(min_length=1, max_length=120)
    label: str = Field(min_length=1, max_length=160)


class AskAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answer: str = Field(min_length=1, max_length=1_200)
    found: bool
    refused: bool = False
    citations: list[Citation] = Field(default_factory=list, max_length=8)


_UNSAFE = re.compile(
    r"\b(approve|approval of|reject|submit|dispatch|receive|release|cancel|delete|remove|update|change|set|"
    r"increase|decrease|edit|override|place an order|send (?:the )?(?:po|order))\b.{0,40}"
    r"\b(po|purchase order|order|transfer|stock|inventory|rule|threshold|line|recommendation)s?\b"
    r"|ignore (?:all |previous |the )?instructions",
    re.I,
)

REFUSAL_TEXT = (
    "I can only read and explain. Approving, rejecting, submitting, dispatching or changing stock and rules is "
    "done by people in the app through the approval screens."
)


@dataclass
class AskResult:
    answer: AskAnswer
    mode: Literal["LLM", "RETRIEVAL_ONLY"]
    loop: LoopResult[AskAnswer] | None = None
    grounded: bool = True
    decision_type: str = "ANSWER_GIVEN"


def ask_baseline(ctx: ToolContext, question: str) -> AskAnswer:
    """No LLM: retrieval only — list the matching sources, no prose (cannot paraphrase without a model)."""
    recs = search_records(ctx, SearchArgs(query=question, limit=3))["items"]
    pols = search_policies(ctx, SearchArgs(query=question, limit=2))["items"]
    remember(ctx, {"r": recs, "p": pols})
    citations = [
        Citation(
            source_type="RECOMMENDATION",
            source_id=str(r["rec_id"]),
            label=f"{r['product']} — {r['store']} ({r['rec_type'].lower()}, {r['qty']})",
        )
        for r in recs
    ] + [
        Citation(source_type="POLICY", source_id=p["section_id"], label=f"{p['document']} — {p['section']}")
        for p in pols
    ]
    if not citations:
        return AskAnswer(
            answer="I could not find this in the recommendations, rules or policies you can see.",
            found=False,
            citations=[],
        )
    lines = [f"- {c.label}" for c in citations]
    return AskAnswer(answer="Matching sources:\n" + "\n".join(lines), found=True, citations=citations)


def answer_question(ctx: ToolContext, question: str, llm: ChatLLM | None, logger: Any = None) -> AskResult:
    if _UNSAFE.search(question):  # defence in depth: the agent has no such tool anyway
        return AskResult(
            AskAnswer(answer=REFUSAL_TEXT, found=False, refused=True),
            "LLM" if llm else "RETRIEVAL_ONLY",
            decision_type="REQUEST_REFUSED",
        )
    if llm is None:
        a = ask_baseline(ctx, question)
        return AskResult(a, "RETRIEVAL_ONLY", decision_type="ANSWER_GIVEN" if a.found else "NOT_FOUND")
    agent = ToolLoopAgent(
        agent_key="ask_retailpilot",
        system_prompt=load_prompt("ask_retailpilot.v1"),
        tools=tools_for("ask_retailpilot"),
        submit_name="submit_answer",
        submit_description="Submit the final answer with citations.",
        output_model=AskAnswer,
        limits=limits_for("ask_retailpilot"),
        llm=llm,
        logger=logger,
    )
    loop = agent.run(ctx, f"Question from a {ctx.role.replace('_', ' ').lower()}: {question}")
    if loop.output is None:  # fail safe: retrieval-only answer
        a = ask_baseline(ctx, question)
        return AskResult(a, "RETRIEVAL_ONLY", loop, decision_type="ANSWER_GIVEN" if a.found else "NOT_FOUND")
    out = loop.output
    # code checks: citations must reference ids a tool returned; numbers must come from tool results (rule 11)
    kept = [c for c in out.citations if c.source_id in ctx.seen_ids or c.source_id == "business_rules"]
    grounded = is_grounded(out.answer, {"n": list(ctx.seen_numbers)}) if out.found else True
    if out.found and (not grounded or not kept):
        a = ask_baseline(ctx, question)
        return AskResult(
            a,
            "RETRIEVAL_ONLY",
            loop,
            grounded=False,
            decision_type="ANSWER_GIVEN" if a.found else "NOT_FOUND",
        )
    out = out.model_copy(update={"citations": kept})
    dtype = "REQUEST_REFUSED" if out.refused else "ANSWER_GIVEN" if out.found else "NOT_FOUND"
    return AskResult(out, "LLM", loop, grounded, dtype)


# =====================================================================================================================
# 2. Data Quality — data analysis / validation
# =====================================================================================================================

Category = Literal["STALE_SKU", "SNAPSHOT_MISMATCH", "SALES_ANOMALY", "MISSING_DATA", "OTHER"]


class DQIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: Category
    likely_cause: str = Field(min_length=5, max_length=300)
    severity: Literal["LOW", "MEDIUM", "HIGH"]
    evidence_ids: list[str] = Field(min_length=1, max_length=10)
    next_step: str = Field(min_length=5, max_length=300)


class DQReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str = Field(min_length=3, max_length=400)
    issues: list[DQIssue] = Field(default_factory=list, max_length=10)


def dq_baseline(report: dict[str, Any]) -> DQReport:
    """SD-02 rules only: one issue per signal type, fixed wording, severity by count."""
    by: dict[str, list[dict[str, Any]]] = {}
    for i in report.get("issues", []):
        by.setdefault(i["signal"], []).append(i)
    issues = []
    if stale := by.get("STALE_SKU"):
        issues.append(
            DQIssue(
                category="STALE_SKU",
                likely_cause="Stock is held but no sales were recorded recently",
                severity="MEDIUM" if len(stale) > 5 else "LOW",
                evidence_ids=[s["evidence_id"] for s in stale[:10]],
                next_step="Check shelf placement and POS item mapping for these SKUs",
            )
        )
    if mism := by.get("SNAPSHOT_MISMATCH"):
        issues.append(
            DQIssue(
                category="SNAPSHOT_MISMATCH",
                likely_cause="POS stock snapshot differs from the ledger",
                severity="MEDIUM",
                evidence_ids=[m["evidence_id"] for m in mism[:10]],
                next_step="Review the reconciliation adjustments with the store",
            )
        )
    return DQReport(
        summary=f"{len(report.get('issues', []))} signals in {len(issues)} groups (rule-based)", issues=issues
    )


@dataclass
class DQResult:
    report: DQReport
    mode: Literal["LLM", "BASELINE"]
    loop: LoopResult[DQReport] | None = None
    drafts: int = 0
    rejected_issues: int = 0


def triage(ctx: ToolContext, llm: ChatLLM | None, logger: Any = None, create_drafts: bool = True) -> DQResult:
    report = get_ingestion_report(ctx, IngestionArgs())
    if not report["issues"]:
        return DQResult(DQReport(summary="No ingestion issues", issues=[]), "BASELINE")
    mode: Literal["LLM", "BASELINE"] = "BASELINE"
    loop = None
    out = None
    if llm is not None:
        agent = ToolLoopAgent(
            agent_key="data_quality",
            system_prompt=load_prompt("data_quality.v1"),
            tools=tools_for("data_quality"),
            submit_name="submit_report",
            submit_description="Submit the triaged data-quality report.",
            output_model=DQReport,
            limits=limits_for("data_quality"),
            llm=llm,
            logger=logger,
        )
        loop = agent.run(ctx, "Triage the latest POS ingestion.")
        out, mode = (loop.output, "LLM") if loop.output else (None, "BASELINE")
    out = out or dq_baseline(report)
    known = ctx.cache.get("ingestion_evidence", {})
    valid = [i for i in out.issues if all(e in known for e in i.evidence_ids)]  # no evidence → no issue
    result = DQResult(
        out.model_copy(update={"issues": valid}), mode, loop, rejected_issues=len(out.issues) - len(valid)
    )
    for issue in valid:
        record_decision(
            ctx.session,
            run_id=ctx.root_run_id,
            agent_key="data_quality",
            decision_type="DATA_ISSUE_CLASSIFIED",
            mode=ctx.mode,
            summary=f"[{issue.severity}] {issue.category}: {issue.likely_cause}",
            evidence_ref={"evidence_ids": issue.evidence_ids, "next_step": issue.next_step},
        )
        if create_drafts and issue.severity in ("MEDIUM", "HIGH"):
            create_data_review_item(
                ctx,
                DataReviewArgs(
                    category=issue.category,
                    summary=issue.next_step,
                    severity=issue.severity,
                    evidence_ids=issue.evidence_ids,
                ),
            )
            result.drafts += 1
    return result


# =====================================================================================================================
# 3. Replenishment Action — workflow / action with approval gate (drafts only)
# =====================================================================================================================


class ActionDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rec_id: str
    action: Literal["TRANSFER_DRAFT", "PO_DRAFT", "NO_ACTION"]
    qty: int = Field(ge=0)
    from_store_id: str | None = None
    rationale: str = Field(min_length=10, max_length=600)


def ra_baseline(ctx: ToolContext, rec_id: str) -> ActionDraft:
    """Deterministic: the largest donor surplus covers what it can (transfer), else order the need."""
    get_recommendation(ctx, RecArgs(rec_id=rec_id))
    opts = get_transfer_options(ctx, TransferOptionsArgs(rec_id=rec_id))
    need = int(opts["need_qty"])
    surplus = ctx.cache.get("donor_surplus", {}).get(rec_id, {})
    if need <= 0:
        return ActionDraft(
            rec_id=rec_id, action="NO_ACTION", qty=0, rationale="Need is 0 at the current position."
        )
    if surplus:
        donor, s = max(surplus.items(), key=lambda kv: kv[1])
        return ActionDraft(
            rec_id=rec_id,
            action="TRANSFER_DRAFT",
            qty=min(need, s),
            from_store_id=donor,
            rationale="Rule-based: transfer the donor's genuine surplus (donor protected).",
        )
    return ActionDraft(
        rec_id=rec_id,
        action="PO_DRAFT",
        qty=need,
        rationale="Rule-based: no surplus anywhere, order the need.",
    )


@dataclass
class RAResult:
    draft: ActionDraft | None
    mode: Literal["LLM", "BASELINE"]
    created: bool
    error: str | None = None
    loop: LoopResult[ActionDraft] | None = None


def draft_for(ctx: ToolContext, rec_id: str, llm: ChatLLM | None, logger: Any = None) -> RAResult:
    mode: Literal["LLM", "BASELINE"] = "BASELINE"
    loop = None
    proposal: ActionDraft | None = None
    if llm is not None:
        agent = ToolLoopAgent(
            agent_key="replenishment_action",
            system_prompt=load_prompt("replenishment_action.v1"),
            tools=[
                t for t in tools_for("replenishment_action") if t.kind == "READ"
            ],  # the write happens below
            submit_name="submit_draft",
            submit_description="Submit the proposal (code validates and drafts it).",
            output_model=ActionDraft,
            limits=limits_for("replenishment_action"),
            llm=llm,
            logger=logger,
        )
        loop = agent.run(ctx, f"Prepare a draft for NEEDS_REVIEW recommendation rec_id={rec_id}.")
        if loop.output and loop.output.rec_id == rec_id:
            proposal, mode = loop.output, "LLM"
    try:
        proposal = proposal or ra_baseline(ctx, rec_id)
        if proposal.action == "NO_ACTION":
            return RAResult(proposal, mode, False, loop=loop)
        if (
            str(rec_id) not in ctx.allowed_qty
        ):  # the model skipped the tools: load the facts before validating
            get_recommendation(ctx, RecArgs(rec_id=rec_id))
            get_transfer_options(ctx, TransferOptionsArgs(rec_id=rec_id))
        create_draft_recommendation(
            ctx,
            DraftArgs(
                rec_id=rec_id,
                draft_type=proposal.action,
                qty=proposal.qty,
                from_store_id=proposal.from_store_id,
                rationale=proposal.rationale,
            ),
        )
        return RAResult(proposal, mode, True, loop=loop)
    except ToolError as exc:  # failed code check (qty not from a tool, donor protection): no draft
        return RAResult(proposal, mode, False, str(exc), loop)


# =====================================================================================================================
# 4. Run Coordinator — coordinator / orchestrator (allow-listed recovery)
# =====================================================================================================================

ActionName = Literal[
    "RETRY_AGENT",
    "MARK_PARTIAL",
    "ESCALATE",
    "INVOKE_DATA_QUALITY",
    "INVOKE_REPLENISHMENT_ACTION",
    "INVOKE_REVIEWER",
    "NO_ACTION",
]


class PlanAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: ActionName
    agent_key: str | None = None
    reason: str = Field(min_length=5, max_length=300)


class CoordinatorPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    actions: list[PlanAction] = Field(min_length=1, max_length=3)


def coordinator_baseline(summary: dict[str, Any]) -> CoordinatorPlan:
    """SD-01 policy as code: escalate critical failures, mark partial otherwise; draft for NEEDS_REVIEW."""
    actions: list[PlanAction] = []
    failed = summary.get("failed_stages", [])
    if any(s.get("critical") for s in failed):
        actions.append(PlanAction(action="ESCALATE", reason="A critical stage failed"))
    elif failed:
        actions.append(PlanAction(action="MARK_PARTIAL", reason="A non-critical stage failed"))
    if summary.get("needs_review_recommendations", 0) > 0:
        actions.append(
            PlanAction(action="INVOKE_REPLENISHMENT_ACTION", reason="NEEDS_REVIEW recommendations exist")
        )
    return CoordinatorPlan(actions=actions[:3] or [PlanAction(action="NO_ACTION", reason="Clean run")])


def validate_plan(plan: CoordinatorPlan, summary: dict[str, Any]) -> tuple[list[PlanAction], list[str]]:
    """Allow-list check in code: no retry of critical / non-failed / already-retried stages; known agents only."""
    failed = {s["agent_key"]: s for s in summary.get("failed_stages", []) if s.get("agent_key")}
    ok: list[PlanAction] = []
    rejected: list[str] = []
    for a in plan.actions:
        if a.action == "RETRY_AGENT":
            spec = BY_KEY.get(a.agent_key or "")
            if spec is None:
                rejected.append(f"retry of {a.agent_key}: unknown agent")
                continue
            if spec.critical:
                rejected.append(
                    f"retry of {a.agent_key}: critical agents are never retried by the coordinator"
                )
                continue
            stage = failed.get(a.agent_key or "")
            if stage is None:
                rejected.append(f"retry of {a.agent_key}: not a failed stage of this run")
                continue
            if stage.get("coordinator_retried"):
                rejected.append(f"retry of {a.agent_key}: already retried")
                continue
        ok.append(a)
    return ok, rejected


@dataclass
class CoordinatorResult:
    plan: CoordinatorPlan
    accepted: list[PlanAction]
    rejected: list[str]
    mode: Literal["LLM", "BASELINE", "SHORT_CIRCUIT"]
    loop: LoopResult[CoordinatorPlan] | None = None


def plan_recovery(ctx: ToolContext, llm: ChatLLM | None, logger: Any = None) -> CoordinatorResult:
    summary = get_exception_summary(ctx, RunLogArgs())
    clean = not summary["failed_stages"] and summary["needs_review_recommendations"] == 0
    if clean:  # stopping condition: clean run → no LLM call
        clean_plan = CoordinatorPlan(
            actions=[PlanAction(action="NO_ACTION", reason="Clean run: no failures or exceptions")]
        )
        return CoordinatorResult(clean_plan, list(clean_plan.actions), [], "SHORT_CIRCUIT")
    loop = None
    plan: CoordinatorPlan | None = None
    mode: Literal["LLM", "BASELINE", "SHORT_CIRCUIT"] = "BASELINE"
    if llm is not None:
        agent = ToolLoopAgent(
            agent_key="run_coordinator",
            system_prompt=load_prompt("run_coordinator.v1"),
            tools=tools_for("run_coordinator"),
            submit_name="submit_plan",
            submit_description="Submit at most 3 allowed actions.",
            output_model=CoordinatorPlan,
            limits=limits_for("run_coordinator"),
            llm=llm,
            logger=logger,
        )
        loop = agent.run(
            ctx, f"Run {summary['run_id']} finished with status {summary['run_status']}. Decide."
        )
        if loop.output:
            plan, mode = loop.output, "LLM"
    plan = plan or coordinator_baseline(summary)
    ok, rejected = validate_plan(plan, summary)
    return CoordinatorResult(plan, ok, rejected, mode, loop)


# =====================================================================================================================
# 5. Recommendation Reviewer — reviewer / evaluator
# =====================================================================================================================

REVIEW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "supported": {"type": "boolean"},
                    "issue": {"type": "string"},
                },
                "required": ["id", "supported", "issue"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["verdicts"],
    "additionalProperties": False,
}


def code_checks(rec: Recommendation) -> list[dict[str, str]]:
    """Deterministic policy checks of one recommendation (always run)."""
    issues: list[dict[str, str]] = []
    ev = rec.evidence or {}
    facts = llm_facts(ev)
    if rec.qty < 0:
        issues.append({"check": "quantity", "message": "Quantity is negative"})
    if rec.explanation and not is_grounded(rec.explanation, facts):
        issues.append(
            {
                "check": "numbers_in_evidence",
                "message": "The explanation states a number that is not in the evidence",
            }
        )
    if rec.explanation:
        private = fact_numbers({k: v for k, v in ev.items() if k in PRIVATE_FIELDS})
        shown = fact_numbers(rec.explanation) - fact_numbers(facts)
        if private & shown:
            issues.append({"check": "scoping", "message": "The explanation reveals another store's stock"})
    if ev.get("kind") == "TRANSFER" and not ev.get("expiring_batch"):
        tq, ds = ev.get("transfer_qty"), ev.get("donor_surplus")
        if isinstance(tq, int) and isinstance(ds, int) and tq > ds:
            issues.append(
                {"check": "donor_protection", "message": f"Transfer {tq} exceeds the donor surplus {ds}"}
            )
        need = ev.get(
            "destination_shortage", ev.get("need_qty")
        )  # TransferEvidence names the need "shortage"
        rem = ev.get("po_remainder_qty")
        if all(isinstance(x, int) for x in (tq, need, rem)) and tq + rem != need:  # type: ignore[operator]
            issues.append(
                {"check": "partial_surplus", "message": "Transfer + order remainder does not equal the need"}
            )
    return issues


@dataclass
class ReviewResult:
    reviewed: int = 0
    flagged: int = 0
    judged_by_llm: int = 0
    llm_calls: int = 0
    tokens: int = 0
    flagged_ids: list[UUID] = field(default_factory=list)


def review_run(
    ctx: ToolContext,
    judge: JsonLLM | None,
    logger: Any = None,
    llm_sample: int = 40,
    batch: int = 20,
    persist: bool = True,
) -> ReviewResult:
    run_id = ctx.scope_run_id
    recs = list(
        ctx.session.scalars(
            select(Recommendation).where(
                Recommendation.run_id == run_id,
                Recommendation.status.in_([RecStatus.PENDING.value, RecStatus.NEEDS_REVIEW.value]),
            )
        )
    )
    result = ReviewResult()
    issues: dict[UUID, list[dict[str, str]]] = {r.rec_id: code_checks(r) for r in recs}
    # LLM judge: groundedness of the WORDING on a sample of explained items (cost bound: llm_sample)
    sample = [r for r in recs if r.explanation][:llm_sample] if judge is not None else []
    prompt = load_prompt("recommendation_reviewer.v1") if sample else ""
    for start in range(0, len(sample), batch):
        chunk = sample[start : start + batch]
        items = [
            {"id": i, "explanation": r.explanation, "facts": llm_facts(r.evidence or {})}
            for i, r in enumerate(chunk)
        ]
        t0 = time.monotonic()
        try:
            reply = judge.complete_json(prompt, json_dumps(items), "review_verdicts", REVIEW_SCHEMA)  # type: ignore[union-attr]
        except LLMError:
            continue  # defined outcome: code checks still apply; these items are judged by code only
        result.llm_calls += 1
        result.tokens += reply.input_tokens + reply.output_tokens
        if logger is not None:
            logger.log_llm_usage(
                run_id=ctx.run_id,
                provider="groq",
                model=reply.model,
                input_tokens=reply.input_tokens,
                output_tokens=reply.output_tokens,
                est_cost=reply.est_cost,
                latency_ms=int((time.monotonic() - t0) * 1000),
            )
        for v in reply.data.get("verdicts", []):
            idx = v.get("id")
            if isinstance(idx, int) and 0 <= idx < len(chunk):
                result.judged_by_llm += 1
                if not v.get("supported", True) and v.get("issue"):
                    issues[chunk[idx].rec_id].append(
                        {"check": "llm_groundedness", "message": str(v["issue"])[:200]}
                    )
    judged = {r.rec_id for r in sample}
    for r in recs:
        found = issues[r.rec_id]
        verdict = "FLAGGED" if found else "PASSED"
        result.reviewed += 1
        if found:
            result.flagged += 1
            result.flagged_ids.append(r.rec_id)
        if not persist:
            continue
        existing = ctx.session.get(RecommendationReview, r.rec_id)
        by = "code+llm" if r.rec_id in judged else "code"
        if existing:
            existing.verdict, existing.issues, existing.judged_by, existing.run_id = (
                verdict,
                found,
                by,
                ctx.root_run_id,
            )
        else:
            ctx.session.add(
                RecommendationReview(
                    rec_id=r.rec_id, run_id=ctx.root_run_id, verdict=verdict, issues=found, judged_by=by
                )
            )
        if found:
            record_decision(
                ctx.session,
                run_id=ctx.root_run_id,
                agent_key="recommendation_reviewer",
                decision_type="REVIEWER_FLAGGED",
                mode=ctx.mode,
                outcome="PENDING",
                store_id=r.store_id,
                product_id=r.product_id,
                rec_id=r.rec_id,
                summary="; ".join(i["message"] for i in found),
                evidence_ref={"checks": [i["check"] for i in found]},
            )
    ctx.session.flush()
    return result


def json_dumps(value: Any) -> str:
    import json

    from app.agents.llm.framework import _jsonable

    return json.dumps(_jsonable(value), ensure_ascii=False)


# =====================================================================================================================
# Pipeline wrappers (BaseAgent) — used by the orchestrator and the manual trigger
# =====================================================================================================================


def _tool_ctx(ctx: RunContext, scope_run_id: UUID | None = None) -> ToolContext:
    mode = ctx.extra.get("mode", "LIVE")
    tctx = ToolContext(
        session=ctx.session,
        role="SUPER_ADMIN",
        store_id=None,
        run_id=ctx.agent_run_id or ctx.run_id,
        scope_run_id=scope_run_id or ctx.extra.get("scope_run_id") or ctx.run_id,
        mode=mode,
    )
    tctx.cache["root_run_id"] = ctx.run_id
    return tctx


class DataQualityAgent(BaseAgent):
    name = "DataQualityAgent"
    critical = False

    def run(self, ctx: RunContext) -> AgentResult:
        res = triage(_tool_ctx(ctx), ctx.extra.get("chat_llm"), ctx.logger)
        return AgentResult(
            status="SUCCESS",
            outputs={
                "mode": res.mode,
                "issues": len(res.report.issues),
                "drafts": res.drafts,
                "rejected_issues": res.rejected_issues,
                "summary": res.report.summary,
                "stop_reason": res.loop.stop_reason if res.loop else "no LLM call",
            },
            step_count=len(res.loop.tools) if res.loop else 1,
        )


class ReplenishmentActionAgent(BaseAgent):
    name = "ReplenishmentActionAgent"
    critical = False
    MAX_PER_RUN = 10

    def run(self, ctx: RunContext) -> AgentResult:
        tctx = _tool_ctx(ctx)
        rec_ids = list(
            ctx.session.scalars(
                select(Recommendation.rec_id)
                .where(
                    Recommendation.run_id == tctx.scope_run_id,
                    Recommendation.status == RecStatus.NEEDS_REVIEW.value,
                )
                .limit(self.MAX_PER_RUN)
            )
        )
        created, modes, errors = 0, {"LLM": 0, "BASELINE": 0}, []
        for rid in rec_ids:
            r = draft_for(tctx, str(rid), ctx.extra.get("chat_llm"), ctx.logger)
            created += int(r.created)
            modes[r.mode] += 1
            if r.error:
                errors.append(r.error[:120])
        return AgentResult(
            status="SUCCESS",
            outputs={
                "needs_review": len(rec_ids),
                "drafts": created,
                "modes": modes,
                "rejected_by_code_checks": errors[:5],
            },
            step_count=len(rec_ids),
        )


class RecommendationReviewerAgent(BaseAgent):
    name = "RecommendationReviewerAgent"
    critical = False

    def run(self, ctx: RunContext) -> AgentResult:
        res = review_run(_tool_ctx(ctx), ctx.extra.get("json_llm"), ctx.logger, persist=True)
        return AgentResult(
            status="SUCCESS",
            outputs={
                "reviewed": res.reviewed,
                "flagged": res.flagged,
                "judged_by_llm": res.judged_by_llm,
                "llm_calls": res.llm_calls,
            },
            step_count=res.llm_calls + 1,
        )


class RunCoordinatorAgent(BaseAgent):
    """Plans recovery; the orchestrator executes the accepted actions (it owns retries and invocations)."""

    name = "RunCoordinatorAgent"
    critical = False

    def run(self, ctx: RunContext) -> AgentResult:
        res = plan_recovery(_tool_ctx(ctx), ctx.extra.get("chat_llm"), ctx.logger)
        ctx.extra["coordinator_actions"] = res.accepted
        return AgentResult(
            status="SUCCESS",
            outputs={
                "mode": res.mode,
                "actions": [a.model_dump() for a in res.accepted],
                "rejected": res.rejected,
            },
            step_count=len(res.accepted),
        )


LLM_AGENT_CLASSES: dict[str, type[BaseAgent]] = {
    "data_quality": DataQualityAgent,
    "replenishment_action": ReplenishmentActionAgent,
    "recommendation_reviewer": RecommendationReviewerAgent,
    "run_coordinator": RunCoordinatorAgent,
}

__all__ = [
    "LLM_AGENT_CLASSES",
    "AskAnswer",
    "answer_question",
    "draft_for",
    "get_evidence",
    "get_run_log",
    "plan_recovery",
    "review_run",
    "triage",
]
