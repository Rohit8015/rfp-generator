"""Phase 7 acceptance test — A9 Router, narrative / structured / boilerplate writers.

Gate: each branch produces the right form, the provenance map is complete, and the
Compliance / Legal / GAP guardrail holds.

Writers that call a model are exercised with a stub provider offline and for real under
the `live` marker. The guardrail and provenance tests are deterministic, because those
are the properties that must hold whatever a model returns.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.agents.generator import GenerationRouter, stakeholder_pack
from src.models.schemas import (
    BuyerProfile,
    ContextPack,
    DeliverableForm,
    EvalCriterion,
    Fit,
    OutlineSection,
    Priority,
    ProofMatch,
    ProvenanceKind,
    ReqType,
    Requirement,
    RetrievedCandidate,
    ReuseDecision,
    SectionStatus,
)
from src.utils import provenance
from src.writers.boilerplate import BoilerplateWriter

ROOT = Path(__file__).parent.parent


# --------------------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------------------


class StubResponse:
    def __init__(self, text: str, parsed=None) -> None:
        self.text = text
        self.parsed = parsed
        self.provider = "stub"
        self.model = "stub"
        self.cached = False


class StubProvider:
    """Returns canned text or a canned parsed object. Records the prompts it saw."""

    def __init__(self, text: str = "", parsed=None) -> None:
        self.text = text
        self.parsed = parsed
        self.prompts: list[str] = []

    def generate(self, prompt, tier="cheap", schema=None, **kw):
        self.prompts.append(prompt)
        return StubResponse(self.text, self.parsed)

    def generate_many(self, prompts, tier="cheap", schema=None, **kw):
        return [self.generate(p, tier, schema) for p in prompts]


def _section(**kw) -> OutlineSection:
    return OutlineSection(
        id=kw.get("id", "S-01"),
        order_index=kw.get("order_index", 0),
        title=kw.get("title", "Recommended approach"),
        purpose=kw.get("purpose", "Explain the proposed solution"),
        requirement_ids=kw.get("requirement_ids", ["R-001"]),
        deliverable_form=kw.get("form", DeliverableForm.PROSE),
        target_words=kw.get("target_words", 400),
    )


def _requirement(rid="R-001", text="The vendor shall implement a lending platform.",
                 **kw) -> Requirement:
    return Requirement(
        id=rid, source_section="2.1", text=text,
        req_type=kw.get("req_type", ReqType.SHALL_REQUIREMENT),
        priority=kw.get("priority", Priority.MANDATORY),
        deliverable_form=kw.get("form", DeliverableForm.PROSE),
    )


def _pack(decision=ReuseDecision.SYNTHESIZE, n=3) -> ContextPack:
    return ContextPack(
        query="q",
        candidates=[
            RetrievedCandidate(chunk_id=f"HQ-00{i}", text=f"Source text {i}. " * 12,
                               source_ref="hq.json", rank=i, dense_score=0.8 - i * 0.05)
            for i in range(1, n + 1)
        ],
        reuse_decision=decision,
        confidence=0.3,
        calibration_version="test-cal",
    )


BUYER = BuyerProfile(
    audience_roles=["Chief Information Officer", "Expert Review Committee"],
    stated_pains=["Onboarding takes too long"],
    evaluation_criteria=[EvalCriterion(name="Technical Solution", weight=35.0)],
    red_lines=["Mandatory requirements are pass/fail"],
    tone_register="professional",
)


# --------------------------------------------------------------------------------------
# Provenance utility
# --------------------------------------------------------------------------------------


def test_prose_sentences_ignores_markdown_scaffolding() -> None:
    md = (
        "## A heading\n\n"
        "First claim here. Second claim here.\n\n"
        "| Col A | Col B |\n|---|---|\n| one | two |\n\n"
        "- A bulleted claim.\n"
        "```\ncode block ignored\n```\n"
    )
    sentences = provenance.prose_sentences(md)
    assert not any(s.startswith("#") for s in sentences)
    assert not any(set(s) <= {"|", "-", " "} for s in sentences)
    assert any("First claim" in s for s in sentences)
    assert any("bulleted claim" in s for s in sentences)
    assert any("one" in s and "two" in s for s in sentences), "table rows need provenance"
    assert not any("code block" in s for s in sentences)


def test_verify_complete_rejects_a_missing_record() -> None:
    from src.models.schemas import GeneratedSection

    section = GeneratedSection(
        section_id="S-01", title="T", deliverable_form=DeliverableForm.PROSE,
        content_md="## T\n\nOne claim. Two claims.\n",
        sentences=provenance.record_sentences("S-01", "## T\n\nOne claim.\n",
                                              ProvenanceKind.TEMPLATE),
    )
    with pytest.raises(provenance.ProvenanceError, match="provenance records"):
        provenance.verify_complete(section)


def test_decision_maps_to_provenance_kind() -> None:
    assert provenance.DECISION_TO_KIND[ReuseDecision.REUSE] is ProvenanceKind.REUSED
    assert provenance.DECISION_TO_KIND[ReuseDecision.ADAPT] is ProvenanceKind.ADAPTED
    assert provenance.DECISION_TO_KIND[ReuseDecision.SYNTHESIZE] is ProvenanceKind.SYNTHESIZED


# --------------------------------------------------------------------------------------
# The guardrail
# --------------------------------------------------------------------------------------


def test_gap_requirement_forces_stakeholder() -> None:
    """CLAUDE.md: a GAP requirement never reaches the narrative writer."""
    router = GenerationRouter(provider=StubProvider("## X\n\nShould never appear.\n"))
    section = _section(requirement_ids=["R-001"])
    matches = [ProofMatch(requirement_id="R-001", fit=Fit.GAP)]

    out = router.generate(section, BUYER, _pack(), [_requirement()], [], matches)
    assert out.status is SectionStatus.ESCALATED
    assert all(r.kind is ProvenanceKind.STAKEHOLDER for r in out.sentences)
    assert "Should never appear" not in out.content_md
    assert out.automated() is False


def test_compliance_section_forces_stakeholder() -> None:
    router = GenerationRouter(provider=StubProvider("## X\n\nDrafted prose.\n"))
    section = _section(title="Security, data protection and compliance")
    out = router.generate(section, BUYER, _pack(), [_requirement()], [], [])
    assert out.status is SectionStatus.ESCALATED
    assert "Drafted prose" not in out.content_md


def test_legal_requirement_forces_stakeholder() -> None:
    router = GenerationRouter(provider=StubProvider("## X\n\nDrafted prose.\n"))
    req = _requirement(text="The vendor shall accept unlimited liability for breach.")
    out = router.generate(_section(), BUYER, _pack(), [req], [], [])
    assert out.status is SectionStatus.ESCALATED
    assert "liability" in " ".join(out.content_md.lower().splitlines())


def test_guardrail_runs_before_any_model_call() -> None:
    """A discarded draft still exists, and drafts get copied. Never generate it."""
    stub = StubProvider("## X\n\nDrafted prose.\n")
    router = GenerationRouter(provider=stub)
    matches = [ProofMatch(requirement_id="R-001", fit=Fit.GAP)]
    router.generate(_section(), BUYER, _pack(), [_requirement()], [], matches)
    assert stub.prompts == [], "the model was called for a guarded section"


def test_ungated_section_is_drafted_normally() -> None:
    stub = StubProvider("## Recommended approach\n\nA drafted claim about delivery.\n")
    router = GenerationRouter(provider=stub)
    out = router.generate(_section(), BUYER, _pack(), [_requirement()], [], [])
    assert out.status is SectionStatus.DRAFTED
    assert stub.prompts, "the model should have been called"
    assert out.automated() is True


def test_stakeholder_pack_needs_no_calibration() -> None:
    pack = stakeholder_pack("S-01")
    assert pack.reuse_decision is ReuseDecision.STAKEHOLDER
    assert pack.calibration_version is None


# --------------------------------------------------------------------------------------
# Routing by deliverable form
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("form,expect_status", [
    (DeliverableForm.COSTING, SectionStatus.ESCALATED),
    (DeliverableForm.GANTT, SectionStatus.ESCALATED),
    (DeliverableForm.CHART, SectionStatus.ESCALATED),
])
def test_phase8_forms_are_escalated_not_guessed(form, expect_status) -> None:
    """Better to escalate than to put invented numbers in front of a client."""
    router = GenerationRouter(provider=StubProvider("## X\n\nInvented figures.\n"))
    out = router.generate(_section(form=form, title="Delivery plan"), BUYER, _pack(),
                          [_requirement(form=form)], [], [])
    assert out.status is expect_status
    assert "Invented figures" not in out.content_md


def test_appendix_routes_to_boilerplate() -> None:
    stub = StubProvider("## X\n\nModel prose.\n")
    router = GenerationRouter(provider=stub)
    section = _section(title="Assumptions", form=DeliverableForm.APPENDIX,
                       purpose="Standard assumptions", requirement_ids=[])
    out = router.generate(section, BUYER, _pack(), [], [], [])
    assert stub.prompts == [], "boilerplate must not call a model"
    assert out.sentences
    assert all(r.kind is ProvenanceKind.TEMPLATE for r in out.sentences)


def test_table_form_routes_to_structured_writer() -> None:
    from src.writers.structured import _Row, _Table

    table = _Table(caption="Team composition.", headers=["Role", "FTE"],
                   rows=[_Row(cells=["Delivery lead", "1"], source_ids=["HQ-001"]),
                         _Row(cells=["Engineer", "4"], source_ids=[])])
    router = GenerationRouter(provider=StubProvider("", parsed=table))
    out = router.generate(_section(title="Team and resourcing", form=DeliverableForm.TABLE),
                          BUYER, _pack(), [_requirement()], [], [])
    assert out.status is SectionStatus.DRAFTED
    assert "| Role | FTE |" in out.content_md
    assert "| Delivery lead | 1 |" in out.content_md


# --------------------------------------------------------------------------------------
# Writers
# --------------------------------------------------------------------------------------


def test_narrative_prompt_carries_buyer_and_themes() -> None:
    from src.models.schemas import WinTheme
    from src.writers.narrative import NarrativeWriter

    stub = StubProvider("## Recommended approach\n\nA claim.\n")
    theme = WinTheme(id="T-01", statement="your onboarding time halves",
                     buyer_pain_addressed="slow onboarding", proof_ids=["PP-001"],
                     requirement_ids_covered=["R-001", "R-002"])
    NarrativeWriter(stub).write(_section(), BUYER, _pack(), [theme])

    prompt = stub.prompts[0]
    assert "Chief Information Officer" in prompt, "buyer audience missing from prompt"
    assert "Technical Solution" in prompt, "evaluation criteria missing from prompt"
    assert "your onboarding time halves" in prompt, "win theme missing from prompt"
    assert "pass/fail" in prompt, "red lines missing from prompt"


def test_narrative_provenance_follows_the_retrieval_decision() -> None:
    from src.writers.narrative import NarrativeWriter

    for decision, kind, expected_sources in [
        (ReuseDecision.REUSE, ProvenanceKind.REUSED, 1),
        (ReuseDecision.ADAPT, ProvenanceKind.ADAPTED, 1),
        (ReuseDecision.SYNTHESIZE, ProvenanceKind.SYNTHESIZED, 3),
    ]:
        out = NarrativeWriter(
            StubProvider("## Recommended approach\n\nA claim about delivery.\n")
        ).write(_section(), BUYER, _pack(decision), [])
        assert all(r.kind is kind for r in out.sentences)
        assert all(len(r.source_ids) == expected_sources for r in out.sentences)


def test_regeneration_reason_reaches_the_prompt() -> None:
    from src.writers.narrative import NarrativeWriter

    stub = StubProvider("## Recommended approach\n\nA claim.\n")
    NarrativeWriter(stub).write(_section(), BUYER, _pack(), [],
                                failure_reason="contradicts the cost total in S-09")
    assert "contradicts the cost total in S-09" in stub.prompts[0]
    assert "REDRAFTED" in stub.prompts[0].upper()


def test_structured_writer_rejects_invented_source_ids() -> None:
    """A cited id the retriever never returned is provenance theatre."""
    from src.writers.structured import StructuredWriter, _Row, _Table

    table = _Table(headers=["Item"], rows=[_Row(cells=["A"], source_ids=["HQ-999"])])
    out = StructuredWriter(StubProvider("", parsed=table)).write(
        _section(form=DeliverableForm.TABLE), BUYER, _pack()
    )
    cited = {s for r in out.sentences for s in r.source_ids}
    assert "HQ-999" not in cited


def test_structured_writer_escapes_pipes() -> None:
    from src.writers.structured import StructuredWriter, _Row, _Table

    table = _Table(headers=["Item"], rows=[_Row(cells=["a | b"], source_ids=[])])
    out = StructuredWriter(StubProvider("", parsed=table)).write(
        _section(form=DeliverableForm.TABLE), BUYER, _pack()
    )
    body = [ln for ln in out.content_md.splitlines() if ln.startswith("|")]
    assert all(ln.count("|") == 2 or "\\|" in ln for ln in body[2:])


def test_boilerplate_leaves_unfilled_placeholders_visible() -> None:
    writer = BoilerplateWriter()
    section = _section(title="Assumptions", form=DeliverableForm.APPENDIX,
                       purpose="Standard assumptions")
    out = writer.write(section, BUYER)
    assert out.sentences
    assert all(r.kind is ProvenanceKind.TEMPLATE for r in out.sentences)
    assert all(not r.source_ids for r in out.sentences)


def test_boilerplate_makes_no_model_call() -> None:
    source = (ROOT / "src" / "writers" / "boilerplate.py").read_text(encoding="utf-8")
    for forbidden in ["get_provider", "generate(", "embed("]:
        assert forbidden not in source.lower(), f"boilerplate.py calls {forbidden}"


# --------------------------------------------------------------------------------------
# Live
# --------------------------------------------------------------------------------------


@pytest.mark.live
def test_live_narrative_section_is_grounded_and_attributed() -> None:
    from src.writers.narrative import NarrativeWriter

    out = NarrativeWriter().write(_section(), BUYER, _pack(ReuseDecision.SYNTHESIZE), [])
    assert out.content_md.strip().startswith("## ")
    assert len(out.content_md.split()) > 40
    provenance.verify_complete(out)
    assert all(r.source_ids for r in out.sentences)


@pytest.mark.live
def test_live_structured_section_renders_a_well_formed_table() -> None:
    from src.writers.structured import StructuredWriter

    out = StructuredWriter().write(
        _section(title="Team and resourcing", form=DeliverableForm.TABLE),
        BUYER, _pack(ReuseDecision.SYNTHESIZE), [_requirement()],
    )
    rows = [ln for ln in out.content_md.splitlines() if ln.strip().startswith("|")]
    assert len(rows) >= 3, "header, separator and at least one row"
    widths = {ln.count("|") for ln in rows}
    assert len(widths) == 1, f"ragged table: column counts {widths}"
    provenance.verify_complete(out)
