"""Streamlit dashboard — Phase 11.

Upload an RFP, run the pipeline with live per-agent progress, and show the requirement
table, the outline, per-section drafts with provenance highlighting, the compliance
matrix, assurance findings, editable sections with save-back, and export.

Run with:  streamlit run app/dashboard.py

Design intent: this is the demo surface, so it shows the things that are hard to believe
without seeing them -- that every sentence is attributable, that gaps are surfaced rather
than written around, and that the arithmetic is checked. The bid/no-bid call and the GAP
list come BEFORE the drafts, because that is the order in which they are useful.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from src.models.schemas import (  # noqa: E402
    RAG,
    Fit,
    Priority,
    ProvenanceKind,
    SectionStatus,
    Severity,
)

#: Colour per provenance kind. The legend is the point of the whole view.
PROVENANCE_COLOURS = {
    ProvenanceKind.REUSED: ("#1b5e20", "#c8e6c9", "lifted from an approved past answer"),
    ProvenanceKind.ADAPTED: ("#0d47a1", "#bbdefb", "a past answer reworked for this buyer"),
    ProvenanceKind.SYNTHESIZED: ("#e65100", "#ffe0b2", "written from several sources"),
    ProvenanceKind.TEMPLATE: ("#37474f", "#cfd8dc", "boilerplate, no model involved"),
    ProvenanceKind.COMPUTED: ("#4a148c", "#e1bee7", "arithmetic, no model involved"),
    ProvenanceKind.STAKEHOLDER: ("#b71c1c", "#ffcdd2", "a human must write this"),
}

RAG_ICON = {RAG.GREEN: "🟢", RAG.AMBER: "🟠", RAG.RED: "🔴"}
FIT_ICON = {Fit.STRONG: "🟢 STRONG", Fit.PARTIAL: "🟠 PARTIAL", Fit.GAP: "🔴 GAP"}


def main() -> None:
    st.set_page_config(page_title="RFP Copilot", page_icon="📄", layout="wide")
    st.title("RFP Copilot")
    st.caption(
        "Turns an RFP into a proposal draft with provenance on every sentence, "
        "gaps surfaced rather than written around, and the arithmetic checked."
    )

    _sidebar()
    if st.session_state.get("result") is None:
        _landing()
    else:
        _results()


# --------------------------------------------------------------------------------------
# Input
# --------------------------------------------------------------------------------------


def _sidebar() -> None:
    from config import get_settings

    settings = get_settings()
    with st.sidebar:
        st.header("Run a bid")

        incoming = sorted((Path(settings.data_path) / "incoming").glob("*.md"))
        choices = ["— upload a file —"] + [p.name for p in incoming]
        picked = st.selectbox("RFP", choices, index=1 if incoming else 0)

        uploaded = None
        if picked == choices[0]:
            uploaded = st.file_uploader("Upload an RFP", type=["md", "txt", "pdf", "docx"])

        live = st.toggle("Use models", value=True,
                         help="Off runs the deterministic path only: no model calls.")

        providers = [p.name for p in settings.available_providers()]
        st.caption(f"Provider chain: {' → '.join(providers) if providers else 'none configured'}")

        if st.button("Run pipeline", type="primary", use_container_width=True):
            path = _resolve_input(settings, picked, uploaded, choices[0])
            if path is None:
                st.error("Choose an RFP or upload one.")
            else:
                _run(path, live)

        if st.session_state.get("result") is not None:
            st.divider()
            if st.button("Clear run", use_container_width=True):
                for key in ("result", "edits"):
                    st.session_state.pop(key, None)
                st.rerun()


def _resolve_input(settings, picked: str, uploaded, upload_label: str) -> Path | None:
    if picked != upload_label:
        return Path(settings.data_path) / "incoming" / picked
    if uploaded is None:
        return None
    target = Path(settings.data_path) / "incoming" / uploaded.name
    target.write_bytes(uploaded.getbuffer())
    return target


def _run(path: Path, live: bool) -> None:
    from src.orchestrator import Orchestrator

    status = st.sidebar.status("Running…", expanded=True)
    bar = st.sidebar.progress(0.0)
    stages = ["A1", "A2", "A3", "A7", "A5", "A6", "A8/A9", "A10-A13",
              "regen", "W1/W2", "W3", "done"]

    def progress(stage: str, message: str) -> None:
        status.write(f"**{stage}** — {message}")
        if stage in stages:
            bar.progress((stages.index(stage) + 1) / len(stages))

    try:
        st.session_state["result"] = Orchestrator(use_llm=live).run(path, progress=progress)
        st.session_state["edits"] = {}
        status.update(label="Complete", state="complete")
    except Exception as exc:  # noqa: BLE001 - surface the failure, do not crash the app
        status.update(label="Failed", state="error")
        st.sidebar.exception(exc)


def _landing() -> None:
    st.info("Pick an RFP in the sidebar and run the pipeline.")
    left, right = st.columns(2)
    with left:
        st.subheader("What this does")
        st.markdown(
            "1. Reads the RFP and types every requirement\n"
            "2. Recommends **bid / partner / no-bid** with reasons\n"
            "3. Says what you can **prove** and what you cannot\n"
            "4. Drafts each section, attributing every sentence\n"
            "5. Checks its own arithmetic, coverage and claims\n"
            "6. Exports docx with the compliance matrix"
        )
    with right:
        st.subheader("Provenance legend")
        for kind, (fg, bg, meaning) in PROVENANCE_COLOURS.items():
            st.markdown(
                f"<span style='background:{bg};color:{fg};padding:2px 8px;"
                f"border-radius:4px;font-weight:600'>{kind.value}</span> "
                f"&nbsp;{meaning}",
                unsafe_allow_html=True,
            )


# --------------------------------------------------------------------------------------
# Results
# --------------------------------------------------------------------------------------


def _results() -> None:
    result = st.session_state["result"]
    report = result.package.report

    a, b, c, d = st.columns(4)
    a.metric("Automation (sections)", f"{report.overall_automation_rate:.0f}%")
    b.metric("Automation (sentences)", f"{_sentence_rate(result):.0f}%")
    c.metric("Requirement coverage", f"{report.compliance_coverage_pct:.0f}%")
    d.metric("Evidence gaps", len(report.gap_requirement_ids))

    tabs = st.tabs([
        "Decide", "Requirements", "Draft", "Compliance", "Assurance", "Tasks", "Export",
    ])
    with tabs[0]:
        _decide(result)
    with tabs[1]:
        _requirements(result)
    with tabs[2]:
        _draft(result)
    with tabs[3]:
        _compliance(result)
    with tabs[4]:
        _assurance(result)
    with tabs[5]:
        _tasks(result)
    with tabs[6]:
        _export(result)


def _sentence_rate(result) -> float:
    from src.utils.metrics import sentence_automation_rate

    return sentence_automation_rate(result.sections)


def _decide(result) -> None:
    """Bid/no-bid and the gap list. The first thing worth knowing, so it is first."""
    st.subheader("Should we bid?")
    st.caption(
        "The highest-return output is a well-reasoned no. Run the qualifier with the "
        "commercial context of this pursuit."
    )

    from src.agents.qualifier import BidQualifier, DealContext

    left, right = st.columns(2)
    with left:
        fit = st.slider("Solution fit %", 0, 100, 80)
        relationship = st.selectbox("Relationship", ["DEEP", "MODERATE", "LIMITED", "NEW"],
                                    index=2)
        incumbent = st.selectbox("Incumbent strength", ["NONE", "WEAK", "MEDIUM", "STRONG"],
                                 index=2)
    with right:
        timing = st.selectbox("Entry timing", ["EARLY", "MID", "LATE"])
        competitors = st.slider("Competitors", 1, 10, 3)
        size = st.slider("Deal size vs normal", 0.3, 2.0, 1.0, 0.1)

    assessment = BidQualifier().assess(DealContext(
        fit_percentage=fit, relationship_depth=relationship, incumbent_strength=incumbent,
        entry_timing=timing, competitor_count=competitors, deal_size_ratio=size,
    ))
    verdict_colour = {"BID": "success", "PARTNER_BID": "warning", "NO_BID": "error"}
    getattr(st, verdict_colour[assessment.verdict.value])(
        f"**{assessment.verdict.value}** — win probability {assessment.winrate_estimate:.0f}%"
    )
    for factor in assessment.driving_factors:
        st.markdown(f"- {factor}")

    st.divider()
    st.subheader("What we cannot prove")
    gaps = [m for m in result.proof_matches if m.fit is Fit.GAP]
    if not gaps:
        st.success("Every requirement has supporting evidence.")
        return
    st.warning(
        f"{len(gaps)} requirement(s) have no supporting proof point. The system will not "
        "write around these — they are carved out of the draft and routed to a human."
    )
    by_id = {r.id: r for r in result.requirements}
    st.dataframe(
        [{"Requirement": m.requirement_id,
          "Priority": by_id[m.requirement_id].priority.value if m.requirement_id in by_id else "",
          "Text": by_id[m.requirement_id].text if m.requirement_id in by_id else "",
          "Why": m.rationale} for m in gaps],
        use_container_width=True, hide_index=True,
    )


def _requirements(result) -> None:
    fits = {m.requirement_id: m.fit for m in result.proof_matches}
    placement = {rid: s.id for s in result.outline.sections for rid in s.requirement_ids}
    st.dataframe(
        [{"ID": r.id,
          "Priority": r.priority.value,
          "Type": r.req_type.value,
          "Renders as": r.deliverable_form.value,
          "Evidence": FIT_ICON.get(fits.get(r.id), ""),
          "Section": placement.get(r.id, "—"),
          "Requirement": r.text,
          "Found by": r.extracted_by} for r in result.requirements],
        use_container_width=True, hide_index=True, height=520,
    )
    st.caption(
        f"{len(result.requirements)} requirements · "
        f"{sum(1 for r in result.requirements if r.priority is Priority.MANDATORY)} mandatory"
    )


def _draft(result) -> None:
    st.caption("Every sentence is coloured by where it came from. Edits are saved back.")
    with st.expander("Provenance legend", expanded=False):
        for kind, (fg, bg, meaning) in PROVENANCE_COLOURS.items():
            st.markdown(
                f"<span style='background:{bg};color:{fg};padding:2px 8px;"
                f"border-radius:4px;font-weight:600'>{kind.value}</span> &nbsp;{meaning}",
                unsafe_allow_html=True,
            )

    for section in result.sections:
        icon = "🔴" if section.status is SectionStatus.ESCALATED else "🟢"
        retries = f" · {section.retry_count} redraft(s)" if section.retry_count else ""
        with st.expander(f"{icon} {section.title} · {section.deliverable_form.value}{retries}",
                         expanded=False):
            mix: dict[str, int] = {}
            for record in section.sentences:
                mix[record.kind.value] = mix.get(record.kind.value, 0) + 1
            st.caption(" · ".join(f"{k} {v}" for k, v in sorted(mix.items())) or "no records")

            st.markdown(_highlight(section), unsafe_allow_html=True)

            for asset in section.asset_paths:
                if Path(asset).is_file():
                    st.image(asset, use_container_width=True)

            edited = st.text_area("Edit", section.content_md, height=220,
                                  key=f"edit_{section.section_id}")
            if st.button("Save", key=f"save_{section.section_id}"):
                section.content_md = edited
                st.session_state.setdefault("edits", {})[section.section_id] = edited
                st.success("Saved. Re-export to include this edit.")


def _highlight(section) -> str:
    """Wrap each recorded sentence in its provenance colour."""
    html = section.content_md
    for record in sorted(section.sentences, key=lambda r: -len(r.sentence)):
        fg, bg, _ = PROVENANCE_COLOURS[record.kind]
        sources = f" [{', '.join(record.source_ids)}]" if record.source_ids else ""
        if record.sentence and record.sentence in html:
            html = html.replace(
                record.sentence,
                f"<span style='background:{bg};color:{fg};padding:1px 3px;"
                f"border-radius:3px' title='{record.kind.value}{sources}'>"
                f"{record.sentence}</span>",
                1,
            )
    return html.replace("\n", "<br>")


def _compliance(result) -> None:
    matrix = result.matrix
    st.metric("Coverage", f"{matrix.coverage_pct:.1f}%")
    st.caption(
        "Measured against what was written, not what was planned. A section that was "
        "escalated and never drafted reduces coverage."
    )
    st.dataframe(
        [{"RAG": RAG_ICON[row.rag],
          "Requirement": row.requirement_id,
          "Priority": row.priority.value,
          "Section": row.section_id or "—",
          "Anchor": row.anchor or "—",
          "Text": row.requirement_text} for row in matrix.rows],
        use_container_width=True, hide_index=True, height=520,
    )


def _assurance(result) -> None:
    consistency = result.consistency
    if consistency.passed:
        st.success(f"No contradictions across {consistency.facts_extracted} extracted facts.")
    else:
        st.error(f"{len(consistency.contradictions)} contradiction(s) found.")
        for contradiction in consistency.contradictions:
            st.markdown(f"- **{contradiction.kind}** "
                        f"({', '.join(contradiction.section_ids)}): {contradiction.detail}")

    st.divider()
    if not result.findings:
        st.info("No assurance findings.")
        return

    order = {Severity.BLOCKER: 0, Severity.WARN: 1, Severity.INFO: 2}
    icon = {Severity.BLOCKER: "🛑", Severity.WARN: "⚠️", Severity.INFO: "ℹ️"}
    st.dataframe(
        [{"": icon[f.severity],
          "Severity": f.severity.value,
          "Type": f.finding_type.value,
          "Section": f.section_id or "—",
          "Detail": f.detail,
          "Evidence": f.evidence[:160]}
         for f in sorted(result.findings, key=lambda f: order[f.severity])],
        use_container_width=True, hide_index=True, height=460,
    )


def _tasks(result) -> None:
    if not result.tasks:
        st.success("No human tasks raised.")
        return
    st.caption("Work the system will not do on its own. Each has an owner.")
    st.dataframe(
        [{"Task": t.id, "Title": t.title, "Owner": t.department,
          "Priority": t.priority.value, "Due": str(t.due_date or "—"),
          "Status": t.status, "Covers": ", ".join(t.requirement_ids) or "—"}
         for t in result.tasks],
        use_container_width=True, hide_index=True, height=420,
    )


def _export(result) -> None:
    package = result.package
    st.subheader("Download")
    for label, path, mime in [
        ("Proposal (Markdown)", package.markdown_path, "text/markdown"),
        ("Proposal (docx)", package.docx_path,
         "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        ("Automation report", package.report_path, "text/markdown"),
    ]:
        if path and Path(path).is_file():
            st.download_button(label, Path(path).read_bytes(), file_name=Path(path).name,
                               mime=mime, use_container_width=True)

    st.divider()
    st.subheader("Where the text came from")
    breakdown = result.package.report.provenance_breakdown
    total = sum(breakdown.values()) or 1
    for kind, count in sorted(breakdown.items(), key=lambda t: -t[1]):
        st.markdown(f"**{kind}** — {count} sentences ({100 * count / total:.0f}%)")
        st.progress(count / total)

    if result.provider_usage:
        st.divider()
        st.subheader("Provider usage")
        st.json(result.provider_usage)


if __name__ == "__main__":
    main()
