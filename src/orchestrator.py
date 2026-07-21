"""Pipeline orchestrator â€” Phase 10.

Chains all four planes and owns the section-level regeneration loop: any section failing
A10-A13 is re-drafted with the failure reason appended to its prompt, max 2 retries,
then escalated to a human task. This loop is what makes the system agentic rather than
a chain.

Concurrency: sections are generated in parallel because they are independent, and the
provider's token buckets keep that from tripping a rate limit. A live classroom run is a
first-class constraint, and serial generation would make it unwatchable.

Failure policy: no single agent failure aborts a run. A section that cannot be drafted is
escalated to a human, which is the same outcome the guardrail produces deliberately.
A run that dies halfway is worth nothing; a run that finishes with six escalations is a
working draft plus a task list.
"""

from __future__ import annotations

import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

from src.agents.architect import ResponseArchitect
from src.agents.buyer_intel import BuyerIntelligence
from src.agents.generator import GenerationRouter, stakeholder_pack
from src.agents.proofs import ProofMatcher, gap_requirement_ids
from src.agents.requirements import RequirementExtractor
from src.agents.retriever import HybridRetriever
from src.agents.structurer import Structurer
from src.agents.win_themes import WinThemeGenerator
from src.assurance.compliance import ComplianceVerifier, coverage_findings
from src.assurance.consistency import ConsistencyChecker
from src.assurance.grounding import GroundednessChecker
from src.assurance.polish import VoicePolisher
from src.models.schemas import (
    AssuranceFinding,
    BuyerProfile,
    ComplianceMatrix,
    ConsistencyReport,
    ContextPack,
    FindingType,
    GeneratedSection,
    OutlineSection,
    ProofMatch,
    Requirement,
    ResponseOutline,
    RunRecord,
    SectionStatus,
    Severity,
    WinTheme,
)
from src.workflow.assembler import Assembler, Package
from src.workflow.router import HumanTask, TaskRouter
from src.workflow.tracker import TaskTracker

log = logging.getLogger(__name__)

MAX_RETRIES = 2


@dataclass
class RunResult:
    """Everything one pipeline execution produced."""

    run: RunRecord
    requirements: list[Requirement] = field(default_factory=list)
    buyer: BuyerProfile | None = None
    themes: list[WinTheme] = field(default_factory=list)
    proof_matches: list[ProofMatch] = field(default_factory=list)
    outline: ResponseOutline | None = None
    sections: list[GeneratedSection] = field(default_factory=list)
    matrix: ComplianceMatrix | None = None
    consistency: ConsistencyReport | None = None
    findings: list[AssuranceFinding] = field(default_factory=list)
    tasks: list[HumanTask] = field(default_factory=list)
    package: Package | None = None
    provider_usage: dict = field(default_factory=dict)

    @property
    def automation_rate(self) -> float:
        return self.package.report.overall_automation_rate if self.package else 0.0


class Orchestrator:
    """Runs the whole pipeline. One public method: run()."""

    def __init__(self, settings=None, provider=None, use_llm: bool = True) -> None:
        if settings is None:
            from config import get_settings

            settings = get_settings()
        self.settings = settings
        self._provider = provider
        self.use_llm = use_llm
        self.timings: dict[str, float] = {}
        #: One retriever for the whole run. Building one per section re-opens Chroma and
        #: unpickles the BM25 index every time, which on a 12-section run is twelve
        #: needless loads and visible dead air in a live demo.
        self._retriever = None

    # --- public ---------------------------------------------------------------------

    def run(
        self,
        rfp_path: Path | str,
        submission_deadline: date | None = None,
        progress=None,
    ) -> RunResult:
        run_id = f"run-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}"
        record = RunRecord(id=run_id, rfp_path=str(rfp_path))
        result = RunResult(run=record)
        report = progress or (lambda *_: None)

        # --- Plane 1: comprehension --------------------------------------------------
        report("A1", "parsing document")
        tree = self._timed("A1_structurer", lambda: Structurer(
            self._provider, use_llm=self.use_llm).parse(rfp_path))

        report("A2", "extracting requirements")
        result.requirements = self._timed("A2_requirements", lambda: RequirementExtractor(
            self._provider, use_llm=self.use_llm).extract(tree))

        report("A3", "profiling the buyer")
        result.buyer = self._timed("A3_buyer_intel", lambda: BuyerIntelligence(
            self._provider, use_llm=self.use_llm).profile(tree))

        # --- Plane 2: strategy -------------------------------------------------------
        # A7 runs before A5 and A6 by necessity: themes must cite proof points, and the
        # architect needs to know which requirements are unevidenced. The progress label
        # leads with the step rather than the agent number so the order reads sensibly.
        report("A7", "matching proof points")
        proofs = ProofMatcher.load_library(self.settings)
        result.proof_matches = self._timed(
            "A7_proofs", lambda: ProofMatcher(proofs).match(result.requirements)
        )

        report("A5", "generating win themes")
        result.themes = self._timed("A5_themes", lambda: WinThemeGenerator(
            self._provider, use_llm=self.use_llm
        ).generate(result.buyer, result.requirements, proofs))

        report("A6", "designing the outline")
        result.outline = self._timed("A6_architect", lambda: ResponseArchitect().design(
            result.requirements, result.buyer, result.themes))

        # --- Plane 3: generation -----------------------------------------------------
        report("A8/A9", f"drafting {len(result.outline.sections)} sections")
        result.sections = self._timed(
            "A9_generation", lambda: self._generate_all(result)
        )

        # --- Plane 4: assurance, then the regeneration loop --------------------------
        report("A10-A13", "checking the draft")
        result.sections = self._timed(
            "regeneration", lambda: self._assure_and_regenerate(result, report)
        )

        result.matrix, result.consistency, result.findings = self._final_assurance(result)

        # --- Workflow ----------------------------------------------------------------
        report("W1/W2", "routing human tasks")
        result.tasks = TaskRouter().route(
            result.sections, result.requirements, result.proof_matches,
            submission_deadline,
        )
        tracker = TaskTracker(tasks=result.tasks)
        tracker.update()

        report("W3", "assembling the package")
        result.package = Assembler(self.settings).assemble(
            run_id=run_id,
            outline=result.outline,
            sections=result.sections,
            matrix=result.matrix,
            consistency=result.consistency,
            findings=result.findings,
            gap_requirement_ids=gap_requirement_ids(result.proof_matches),
            tasks_markdown=tracker.render(),
            title=tree.title or "Proposal response",
        )

        self._finalise(record, result)
        report("done", f"automation rate {result.automation_rate:.1f}%")
        return result

    # --- generation -----------------------------------------------------------------

    def _generate_all(self, result: RunResult) -> list[GeneratedSection]:
        """Draft every section concurrently. Independent work, so run it in parallel."""
        router = GenerationRouter(self._provider, self.settings)
        sections = result.outline.sections
        workers = min(self.settings.llm_max_concurrency, max(1, len(sections)))

        # Open the indices before any concurrency starts. Left lazy, the first several
        # sections race to construct the Chroma client and all but one fail with
        # "could not connect to tenant default_tenant", silently degrading those
        # sections to a stakeholder pack.
        self._warm_retriever()

        with ThreadPoolExecutor(max_workers=workers) as pool:
            return list(pool.map(
                lambda s: self._generate_one(router, s, result), sections
            ))

    def _generate_one(
        self,
        router: GenerationRouter,
        section: OutlineSection,
        result: RunResult,
        failure_reason: str | None = None,
    ) -> GeneratedSection:
        pack = self._retrieve(section, result)
        themes = [t for t in result.themes
                  if not t.dropped and t.id in set(section.themes_to_carry)]
        try:
            return router.generate(
                section, result.buyer, pack, result.requirements, themes,
                result.proof_matches, failure_reason,
            )
        except Exception as exc:  # noqa: BLE001 - one bad section must not kill the run
            log.warning("section %s failed to generate: %s", section.id, exc)
            return GenerationRouter._stakeholder_brief(
                section,
                [r for r in result.requirements if r.id in set(section.requirement_ids)],
                f"generation failed: {type(exc).__name__}",
            )

    def _warm_retriever(self) -> None:
        """Build the retriever and open its indices, single-threaded."""
        try:
            if self._retriever is None:
                self._retriever = HybridRetriever(self.settings, self._provider)
            self._retriever.warm()
        except Exception as exc:  # noqa: BLE001 - degrade to stakeholder packs, loudly
            log.warning("retrieval unavailable for this run: %s", exc)
            self._retriever = None

    def _retrieve(self, section: OutlineSection, result: RunResult) -> ContextPack:
        """Retrieve for a section, degrading to a stakeholder pack if retrieval fails."""
        reqs = [r for r in result.requirements if r.id in set(section.requirement_ids)]
        query = " ".join([section.title, section.purpose,
                          *(r.text for r in reqs[:5])])[:900]
        try:
            if self._retriever is None:
                self._retriever = HybridRetriever(self.settings, self._provider)
            return self._retriever.retrieve(
                query, top_k=5, paraphrase=" ".join(r.text for r in reqs[:3])[:400],
                section_purpose=section.purpose,
            )
        except Exception as exc:  # noqa: BLE001 - no index, no calibration, no network
            log.warning("retrieval failed for %s: %s", section.id, exc)
            return stakeholder_pack(section.id)

    # --- the regeneration loop ------------------------------------------------------

    def _assure_and_regenerate(self, result: RunResult, report) -> list[GeneratedSection]:
        """Re-draft failing sections with the reason fed back. Max 2 retries, then escalate.

        This is the loop that makes the system agentic. A section is only regenerated for
        problems a rewrite can fix; a stakeholder brief is never "fixed" by redrafting.
        """
        sections = result.sections
        router = GenerationRouter(self._provider, self.settings)
        by_id = {s.id: s for s in result.outline.sections}

        for attempt in range(1, MAX_RETRIES + 1):
            reasons = self._section_failures(sections)
            if not reasons:
                break

            report("regen", f"attempt {attempt}: redrafting {len(reasons)} section(s)")
            updated = {s.section_id: s for s in sections}
            for section_id, reason in reasons.items():
                outline_section = by_id.get(section_id)
                if outline_section is None:
                    continue
                redrafted = self._generate_one(router, outline_section, result, reason)
                redrafted.retry_count = attempt
                if redrafted.status is SectionStatus.ESCALATED:
                    # The guardrail or a failure sent it to a human; stop retrying.
                    updated[section_id] = redrafted
                    continue
                updated[section_id] = redrafted
            sections = list(updated.values())

        # Anything still failing after the retry budget goes to a human.
        remaining = self._section_failures(sections)
        final: list[GeneratedSection] = []
        for section in sections:
            reason = remaining.get(section.section_id)
            if reason and section.status is not SectionStatus.ESCALATED:
                outline_section = by_id.get(section.section_id)
                escalated = GenerationRouter._stakeholder_brief(
                    outline_section,
                    [r for r in result.requirements
                     if r.id in set(outline_section.requirement_ids)],
                    f"failed assurance after {MAX_RETRIES} redrafts: {reason}",
                )
                escalated.retry_count = MAX_RETRIES
                final.append(escalated)
            else:
                final.append(section)
        return final

    def _section_failures(self, sections: list[GeneratedSection]) -> dict[str, str]:
        """Per-section problems a redraft could plausibly fix."""
        drafted = [s for s in sections if s.status is SectionStatus.DRAFTED]
        if not drafted:
            return {}

        failures: dict[str, str] = {}

        for contradiction in ConsistencyChecker().check(drafted).contradictions:
            for section_id in contradiction.section_ids:
                failures.setdefault(section_id, f"{contradiction.kind}: {contradiction.detail}")

        for finding in VoicePolisher().review(drafted):
            if finding.severity is Severity.BLOCKER and finding.section_id:
                failures.setdefault(finding.section_id, f"risk language â€” {finding.detail}")

        # Groundedness deliberately does NOT drive regeneration. A12 returns advisory
        # flags at WARN severity, and the plan names false positives as a live risk.
        # Letting an advisory flag escalate a section after two redrafts turned every
        # false positive into a human task -- including one raised because the sources
        # "do not mention Akshaya Finance Limited", which is the buyer's own name.
        # Grounding findings still reach the assurance report for human review.
        return failures

    # --- final assurance ------------------------------------------------------------

    def _final_assurance(
        self, result: RunResult
    ) -> tuple[ComplianceMatrix, ConsistencyReport, list[AssuranceFinding]]:
        matrix = ComplianceVerifier().verify(
            result.requirements, result.outline, result.sections
        )
        consistency = ConsistencyChecker().check(result.sections)

        findings: list[AssuranceFinding] = list(coverage_findings(matrix))
        findings.extend(VoicePolisher().review(result.sections))
        for contradiction in consistency.contradictions:
            findings.append(AssuranceFinding(
                finding_type=FindingType.CONTRADICTION,
                severity=Severity.BLOCKER,
                detail=contradiction.detail,
                section_id=(contradiction.section_ids[0]
                            if contradiction.section_ids else None),
                evidence="; ".join(contradiction.values),
            ))
        if self.use_llm:
            try:
                findings.extend(GroundednessChecker(self._provider).check(result.sections))
            except Exception as exc:  # noqa: BLE001 - grounding is advisory
                log.warning("final grounding check skipped: %s", exc)
        return matrix, consistency, findings

    # --- bookkeeping ----------------------------------------------------------------

    def _timed(self, name: str, fn):
        start = time.time()
        try:
            return fn()
        finally:
            self.timings[name] = round(time.time() - start, 2)

    def _finalise(self, record: RunRecord, result: RunResult) -> None:
        record.finished_at = datetime.now(timezone.utc)
        record.status = "COMPLETE"
        record.mode = result.outline.mode if result.outline else None
        record.sections_total = len(result.sections)
        record.sections_automated = sum(1 for s in result.sections if s.automated())
        record.automation_rate = result.automation_rate
        record.timings = dict(self.timings)

        usage: dict = {}
        try:
            provider = self._provider
            if provider is None:
                from src.llm.provider import get_provider

                provider = get_provider()
            usage = provider.usage_summary()
        except Exception:  # noqa: BLE001 - usage is telemetry, not a result
            usage = {}
        result.provider_usage = usage
        record.token_counts = {
            "prompt": int(usage.get("prompt_tokens", 0)),
            "completion": int(usage.get("completion_tokens", 0)),
        }
        self._persist(record)

    def _persist(self, record: RunRecord) -> None:
        try:
            from src.models import db

            conn = db.connect(self.settings.sqlite_path)
            db.init_db(conn)
            db.save_run(conn, record)
            conn.close()
        except Exception as exc:  # noqa: BLE001 - telemetry failure is not run failure
            log.warning("could not persist run record: %s", exc)


def main() -> None:
    """One command: RFP in, full package out."""
    import argparse

    parser = argparse.ArgumentParser(description="Run the RFP Copilot pipeline.")
    parser.add_argument("rfp", help="path to the RFP document")
    parser.add_argument("--offline", action="store_true",
                        help="deterministic path only; no model calls")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

    def progress(stage: str, message: str) -> None:
        print(f"  [{stage}] {message}", flush=True)

    result = Orchestrator(use_llm=not args.offline).run(args.rfp, progress=progress)
    package = result.package

    print("\n" + "=" * 70)
    print(f"automation rate      : {result.automation_rate:.1f}%")
    print(f"requirement coverage : {result.matrix.coverage_pct:.1f}%")
    print(f"consistency          : {'passed' if result.consistency.passed else 'FAILED'}")
    print(f"human tasks raised   : {len(result.tasks)}")
    print(f"markdown             : {package.markdown_path}")
    print(f"docx                 : {package.docx_path}")
    print(f"automation report    : {package.report_path}")


if __name__ == "__main__":
    main()
