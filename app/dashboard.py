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


def _load_secrets_into_env() -> None:
    """Bridge Streamlit Cloud secrets into the environment.

    Streamlit Community Cloud stores secrets in st.secrets, not as environment
    variables, but config.py reads the environment (pydantic-settings). Copying them
    across lets the identical settings work in three places without change: a local
    .env file, real environment variables, and the Streamlit Cloud secrets manager.

    Runs before any config import, so the settings singleton is built with the keys
    already present. A missing secrets file locally is expected -- .env covers that.
    """
    import os

    try:
        for key, value in st.secrets.items():
            if isinstance(value, (str, int, float)):
                os.environ.setdefault(key, str(value))
    except Exception:  # noqa: BLE001 - no secrets file is a normal local state
        pass


@st.cache_resource(show_spinner=False)
def _bootstrap() -> bool:
    """Build the search indices on first run. Cached, so it happens once per deploy."""
    from src.bootstrap import ensure_indices

    with st.spinner("Preparing the search index (first run only, ~1 minute)…"):
        return ensure_indices()


def main() -> None:
    _load_secrets_into_env()  # must run before any config import
    st.set_page_config(page_title="RFP Copilot", page_icon="📄", layout="wide")
    st.title("RFP Copilot")
    st.caption(
        "Turns an RFP into a proposal draft with provenance on every sentence, "
        "gaps surfaced rather than written around, and the arithmetic checked."
    )

    _bootstrap()
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

        # The pipeline always runs with the language models on. The deterministic-only
        # path still exists in code (Orchestrator(use_llm=False)) for tests and offline
        # use, but it is not offered in the UI.
        providers = [p.name for p in settings.available_providers()]
        st.caption(
            f"Provider chain: {' → '.join(providers) if providers else 'none configured'}"
        )

        if st.button("Run pipeline", type="primary", use_container_width=True):
            path = _resolve_input(settings, picked, uploaded, choices[0])
            if path is None:
                st.error("Choose an RFP or upload one.")
            else:
                _run(path, live=True)

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
    # Execution order, not numeric order. A7 precedes A5/A6 because win themes must cite
    # proof points and the architect needs to know which requirements are unevidenced.
    stages = ["A1", "A2", "A3", "A7", "A5", "A6", "A8/A9", "A10-A13",
              "regen", "W1/W2", "W3", "done"]
    labels = {
        "A1": "Parsing the document", "A2": "Extracting requirements",
        "A3": "Profiling the buyer", "A7": "Matching proof points",
        "A5": "Generating win themes", "A6": "Designing the outline",
        "A8/A9": "Retrieving and drafting", "A10-A13": "Checking the draft",
        "regen": "Redrafting failures", "W1/W2": "Routing human tasks",
        "W3": "Assembling the package", "done": "Complete",
    }

    def progress(stage: str, message: str) -> None:
        step = stages.index(stage) + 1 if stage in stages else 0
        heading = labels.get(stage, stage)
        status.write(f"**{step}/{len(stages)} · {heading}** ({stage}) — {message}")
        if step:
            bar.progress(step / len(stages))

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

    # Short labels: at normal window width the cards clip anything longer, which made
    # the two automation figures indistinguishable. The detail lives in the help text.
    fully = sum(1 for s in result.sections if s.automated())
    escalated = sum(1 for s in result.sections
                    if s.status is SectionStatus.ESCALATED)
    partial = len(result.sections) - fully - escalated

    a, b, c, d = st.columns(4)
    a.metric("Sections clean", f"{fully}/{len(result.sections)}",
             help="Sections where no sentence needed a human. Deliberately strict: one "
                  "carved-out requirement disqualifies the whole section.")
    b.metric("Sentences auto", f"{_sentence_rate(result):.0f}%",
             help="Share of sentences produced without human input. The informative "
                  "figure when most sections carry a small carve-out.")
    c.metric("Coverage", f"{report.compliance_coverage_pct:.0f}%",
             help="Requirements traced to drafted content, not merely planned for.")
    d.metric("Evidence gaps", len(report.gap_requirement_ids),
             help="Requirements with no supporting proof point. Carved out, never "
                  "written around.")

    if partial:
        st.caption(
            f"{fully} section(s) needed no human input · {partial} drafted with "
            f"carve-outs · {escalated} escalated entirely."
        )

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
        "Set the commercial situation of this pursuit and the qualifier scores it. "
        "The verdict below is a recommendation, not a gate — and a well-reasoned no "
        "is worth as much as a yes, because it redirects the effort."
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
        # Status columns are pinned small and the long text column absorbs the rest, so
        # Evidence and Section stay readable instead of being clipped to "PAR…".
        column_config={
            "ID": st.column_config.TextColumn(width="small"),
            "Priority": st.column_config.TextColumn(width="small"),
            "Type": st.column_config.TextColumn(width="small"),
            "Renders as": st.column_config.TextColumn(width="small"),
            "Evidence": st.column_config.TextColumn(width="small"),
            "Section": st.column_config.TextColumn(width="small"),
            "Requirement": st.column_config.TextColumn(width="large"),
            "Found by": st.column_config.TextColumn(width="small"),
        },
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
    """Colour each recorded sentence by provenance, leaving markdown structure intact.

    Two things this must not do, both of which it did originally:

    - Convert newlines to <br>. Markdown needs its line structure to know where a
      heading ends, so "## Title" followed by a <br> swallowed the entire section body
      into one giant heading.
    - Wrap a table row in a span. A row that starts with anything other than a pipe
      stops being a table row, so highlighting rendered tables as literal pipe text.
      Table rows are left alone; their provenance is visible in the counts above.
    """
    lines_out: list[str] = []
    by_sentence = sorted(section.sentences, key=lambda r: -len(r.sentence))

    for line in section.content_md.splitlines():
        stripped = line.strip()
        # Structure passes through untouched: headings, table rows, block quotes, rules.
        if (not stripped or stripped.startswith(("#", "|", ">", "---", "```"))):
            lines_out.append(line)
            continue

        rendered = line
        for record in by_sentence:
            if not record.sentence or record.sentence not in rendered:
                continue
            fg, bg, _ = PROVENANCE_COLOURS[record.kind]
            sources = f" · {', '.join(record.source_ids)}" if record.source_ids else ""
            rendered = rendered.replace(
                record.sentence,
                f"<span style='background:{bg};color:{fg};padding:1px 4px;"
                f"border-radius:3px' title='{record.kind.value}{sources}'>"
                f"{record.sentence}</span>",
                1,
            )
        lines_out.append(rendered)

    return "\n".join(lines_out)


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
        column_config={
            "RAG": st.column_config.TextColumn(width="small"),
            "Requirement": st.column_config.TextColumn(width="small"),
            "Priority": st.column_config.TextColumn(width="small"),
            "Section": st.column_config.TextColumn(width="small"),
            "Anchor": st.column_config.TextColumn(width="small"),
            "Text": st.column_config.TextColumn(width="large"),
        },
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
        column_config={
            "": st.column_config.TextColumn(width="small"),
            "Severity": st.column_config.TextColumn(width="small"),
            "Type": st.column_config.TextColumn(width="small"),
            "Section": st.column_config.TextColumn(width="small"),
            "Detail": st.column_config.TextColumn(width="large"),
            "Evidence": st.column_config.TextColumn(width="medium"),
        },
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
    st.caption(
        "All six provenance kinds are listed, including those this run did not produce, "
        "so the breakdown matches the legend."
    )
    breakdown = dict(result.package.report.provenance_breakdown)
    for kind in ProvenanceKind:  # ensure every legend entry has a row, even at zero
        breakdown.setdefault(kind.value, 0)
    total = sum(breakdown.values()) or 1
    for kind, count in sorted(breakdown.items(), key=lambda t: -t[1]):
        share = count / total
        st.markdown(f"**{kind}** — {count} sentences ({100 * share:.0f}%)")
        st.progress(share)

    st.divider()
    _model_usage(result)


def _model_usage(result) -> None:
    """Detailed token and call usage for the run.

    Reads every value defensively with .get(), so a run produced by an older code
    version (whose usage dict lacks the enriched keys) renders rather than crashing.
    """
    usage = result.provider_usage or {}
    st.subheader("Model usage this run")

    calls = usage.get("calls", 0)
    if not calls:
        st.info(
            "No live model calls — this was a deterministic run, or every call was served "
            "from cache. Token usage applies only to generative calls; the local "
            "embedding and reranking models are not metered."
        )
        return

    cached = usage.get("cached", 0)
    live = usage.get("live_calls", calls - cached)
    prompt = usage.get("prompt_tokens", 0)
    completion = usage.get("completion_tokens", 0)
    total = usage.get("total_tokens", prompt + completion)
    cache_rate = usage.get("cache_hit_rate", (cached / calls) if calls else 0.0)
    avg_tokens = usage.get("avg_tokens_per_call", round(total / calls) if calls else 0)
    total_latency = usage.get("total_latency_s", 0.0)
    avg_latency = usage.get("avg_latency_s", 0.0)

    # Headline metrics
    a, b, c, d = st.columns(4)
    a.metric("Model calls", calls, help=f"{live} live · {cached} from cache")
    b.metric("Total tokens", f"{total:,}",
             help=f"{prompt:,} prompt (in) · {completion:,} completion (out) · "
                  f"~{avg_tokens:,} per call")
    c.metric("Cache hit rate", f"{cache_rate * 100:.0f}%",
             help="Share of calls served from the content-hash cache — free and instant.")
    d.metric("Total latency", f"{total_latency:.1f}s",
             help=f"~{avg_latency:.2f}s per call (live calls only)")

    # Prompt vs completion split
    prompt_share = prompt / (total or 1)
    st.caption(
        f"**Token split** — {prompt:,} in ({prompt_share * 100:.0f}%) · "
        f"{completion:,} out ({(1 - prompt_share) * 100:.0f}%). Input dominates because "
        "each prompt carries the buyer profile, win themes and retrieved context."
    )

    by_model = usage.get("by_model", {})
    if by_model:
        st.markdown("**By model**")
        st.dataframe(
            [{"Model": model,
              "Calls": v.get("calls", 0),
              "Cached": v.get("cached", 0),
              "Prompt tokens": f"{v.get('prompt_tokens', 0):,}",
              "Completion tokens": f"{v.get('completion_tokens', 0):,}",
              "Total tokens": f"{v.get('total_tokens', 0):,}",
              "Avg latency (s)": v.get("avg_latency_s", 0.0)}
             for model, v in sorted(by_model.items(),
                                    key=lambda kv: -kv[1].get("total_tokens", 0))],
            use_container_width=True, hide_index=True,
        )

    by_tier = usage.get("by_tier", {})
    by_provider = usage.get("by_provider", {})
    if by_tier or by_provider:
        left, right = st.columns(2)
        with left:
            if by_tier:
                st.markdown("**By tier**")
                st.caption("cheap = light tasks · strong = drafting and assurance")
                st.dataframe(
                    [{"Tier": tier, "Calls": v.get("calls", 0),
                      "Total tokens": f"{v.get('total_tokens', 0):,}"}
                     for tier, v in sorted(by_tier.items())],
                    use_container_width=True, hide_index=True,
                )
        with right:
            if by_provider:
                st.markdown("**By provider**")
                st.caption("which free tier actually served each call, after failover")
                st.dataframe(
                    [{"Provider": prov, "Calls": v.get("calls", 0),
                      "Total tokens": f"{v.get('total_tokens', 0):,}",
                      "Avg latency (s)": v.get("avg_latency_s", 0.0)}
                     for prov, v in sorted(by_provider.items(),
                                           key=lambda kv: -kv[1].get("calls", 0))],
                    use_container_width=True, hide_index=True,
                )

    with st.expander("Raw usage JSON"):
        st.json(usage)


if __name__ == "__main__":
    main()
