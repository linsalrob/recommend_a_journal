"""Read-only Streamlit app for the journal recommender."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import streamlit as st

from journal_recommender.streamlit_helpers import (
    build_metrics_audit_for_app,
    example_feature_files,
    filter_journals,
    filter_options,
    journal_detail,
    journal_table_rows,
    load_journals_for_app,
    metrics_summary,
    missing_metric_rows,
    parse_manuscript_yaml_text,
    recommendation_markdown,
    recommendation_table_rows,
    score_manuscript_yaml_text,
)

DEFAULT_JOURNALS_PATH = Path("data/journals.yaml")
DEFAULT_EXAMPLES_DIR = Path("data/examples")


st.set_page_config(page_title="Journal Recommender", layout="wide")


@st.cache_data(show_spinner=False)
def cached_load_journals(journals_path: str):
    return load_journals_for_app(journals_path)


def main() -> None:
    st.sidebar.title("Configuration")
    journals_path = Path(
        st.sidebar.text_input("Journals path", str(DEFAULT_JOURNALS_PATH))
    )
    examples_dir = Path(
        st.sidebar.text_input("Examples directory", str(DEFAULT_EXAMPLES_DIR))
    )

    journals = load_journals_or_stop(journals_path)

    page = st.sidebar.radio(
        "Page",
        ["Home / Overview", "Journal Database", "Rank Manuscript", "Metrics Audit"],
    )

    st.sidebar.info(
        "This first app version expects structured manuscript-feature YAML. "
        "Do not upload confidential DOCX/PDF manuscripts unless running locally "
        "and you understand where files are stored."
    )

    if page == "Home / Overview":
        render_home(journals_path, journals)
    elif page == "Journal Database":
        render_journal_database(journals)
    elif page == "Rank Manuscript":
        render_rank_manuscript(journals, examples_dir)
    elif page == "Metrics Audit":
        render_metrics_audit(journals)


def load_journals_or_stop(journals_path: Path):
    if not journals_path.exists():
        st.error(f"Journal database path does not exist: `{journals_path}`")
        st.stop()
    try:
        return cached_load_journals(str(journals_path))
    except Exception as exc:  # pragma: no cover - UI error rendering
        st.error(f"Could not load journal database: {exc}")
        st.stop()


def render_home(journals_path: Path, journals: list[Any]) -> None:
    st.title("Journal Recommender")
    st.write(
        "Evidence-based journal recommendation tooling for microbiome, "
        "metagenomics, microbial genomics, viromics, phage biology, microbial "
        "ecology, computational biology, and related manuscripts."
    )
    st.warning(
        "This app is read-only. It does not modify `data/journals.yaml`, run "
        "publisher updates, parse DOCX/PDF manuscripts, or call an LLM."
    )

    last_checked = sorted(
        {journal.last_checked for journal in journals if journal.last_checked}
    )
    columns = st.columns(3)
    columns[0].metric("Journals loaded", len(journals))
    columns[1].metric("Database path", str(journals_path))
    columns[2].metric(
        "Last checked dates",
        ", ".join(last_checked[-3:]) if last_checked else "not recorded",
    )


def render_journal_database(journals: list[Any]) -> None:
    st.title("Journal Database")
    options = filter_options(journals)

    with st.sidebar:
        st.subheader("Journal filters")
        publisher = select_filter("Publisher", options["publishers"])
        scope_tag = select_filter("Scope tag", options["scope_tags"])
        manuscript_tag = select_filter("Manuscript tag", options["manuscript_tags"])
        open_access_model = select_filter(
            "Open access model",
            options["open_access_models"],
        )
        quartile = select_filter("Quartile", options["quartiles"])

    filtered = filter_journals(
        journals,
        publisher=publisher,
        scope_tag=scope_tag,
        manuscript_tag=manuscript_tag,
        open_access_model=open_access_model,
        quartile=quartile,
    )
    st.caption(f"Showing {len(filtered)} of {len(journals)} journals.")
    st.dataframe(journal_table_rows(filtered), use_container_width=True)

    if not filtered:
        return
    selected_name = st.selectbox(
        "Select a journal for details",
        [journal.journal for journal in filtered],
    )
    selected = next(journal for journal in filtered if journal.journal == selected_name)
    render_journal_detail(journal_detail(selected))


def render_journal_detail(detail: dict[str, Any]) -> None:
    st.subheader(detail["journal"])
    left, right = st.columns(2)
    with left:
        st.markdown("**URLs**")
        st.json(detail["urls"], expanded=False)
        st.markdown("**Data policy summary**")
        st.write(detail["data_policy_summary"] or "Not curated.")
        st.markdown("**Code policy summary**")
        st.write(detail["code_policy_summary"] or "Not curated.")
    with right:
        st.markdown("**Suitable for**")
        st.write(detail["suitable_for"] or "Not curated.")
        st.markdown("**Less suitable for**")
        st.write(detail["less_suitable_for"] or "Not curated.")
        st.markdown("**Metrics and sources**")
        st.json(detail["metrics"], expanded=False)

    with st.expander("Source evidence"):
        st.dataframe(detail["source_evidence"], use_container_width=True)


def render_rank_manuscript(journals: list[Any], examples_dir: Path) -> None:
    st.title("Rank Manuscript")
    st.info(
        "Provide structured manuscript-feature YAML only. DOCX/PDF parsing is "
        "not implemented in this app version."
    )

    yaml_text = manuscript_yaml_input(examples_dir)
    if not yaml_text.strip():
        st.stop()

    try:
        manuscript = parse_manuscript_yaml_text(yaml_text)
    except Exception as exc:
        st.error(f"Invalid manuscript feature YAML: {exc}")
        st.stop()

    st.success(f"Validated manuscript features for: {manuscript.title or 'untitled'}")

    if not st.button("Rank journals", type="primary"):
        st.stop()

    try:
        recommendations = score_manuscript_yaml_text(yaml_text, journals)
    except Exception as exc:  # pragma: no cover - defensive UI error
        st.error(f"Could not rank journals: {exc}")
        st.stop()

    st.subheader("Summary")
    top = recommendations.scores[0]
    cols = st.columns(5)
    cols[0].metric("Top recommendation", top.journal, f"{top.total_score:.1f}")
    cols[1].metric("Strategic target", recommendations.best_strategic_target.journal)
    cols[2].metric("Current fit", recommendations.best_current_fit.journal)
    cols[3].metric("Safest credible", recommendations.safest_credible_journal.journal)
    cols[4].metric("Aspirational", recommendations.aspirational_journal.journal)

    st.subheader("Ranked Shortlist")
    st.dataframe(recommendation_table_rows(recommendations), use_container_width=True)

    st.subheader("Journal Details")
    for score in recommendations.scores[:10]:
        with st.expander(f"{score.journal} - {score.total_score:.1f}/100"):
            st.json(score.component_scores, expanded=False)
            st.markdown("**Matched tags**")
            st.write(score.matched_tags or "None.")
            st.markdown("**Rationale**")
            st.write(score.rationale_bullets or "No rationale generated.")
            st.markdown("**Desk-rejection risks**")
            st.write(score.desk_rejection_risks or "No major risk from tags.")
            st.markdown("**Evidence fields used**")
            st.write(score.evidence_fields_used or "None.")
            st.markdown("**Prestige metrics used**")
            st.write(score.prestige_score_source or "Not available.")
            st.write(score.key_metrics_used or "No curated metric values used.")
            if score.prestige_fallback_warning:
                st.warning(score.prestige_fallback_warning)

    markdown = recommendation_markdown(recommendations)
    st.download_button(
        "Download Markdown recommendation report",
        markdown,
        file_name="journal_recommendation.md",
        mime="text/markdown",
    )
    with st.expander("Markdown report preview"):
        st.markdown(markdown)


def manuscript_yaml_input(examples_dir: Path) -> str:
    source = st.radio(
        "Manuscript feature source",
        ["Example file", "Upload YAML", "Paste YAML"],
        horizontal=True,
    )

    if source == "Example file":
        examples = example_feature_files(examples_dir)
        if not examples:
            st.error(f"No example YAML files found in `{examples_dir}`.")
            return ""
        selected = st.selectbox("Example file", examples, format_func=lambda p: p.name)
        return selected.read_text(encoding="utf-8")

    if source == "Upload YAML":
        uploaded = st.file_uploader(
            "Upload manuscript-feature YAML",
            type=["yaml", "yml"],
        )
        if uploaded is None:
            return ""
        return uploaded.getvalue().decode("utf-8")

    return st.text_area("Paste manuscript-feature YAML", height=360)


def render_metrics_audit(journals: list[Any]) -> None:
    st.title("Metrics Audit")
    audit = build_metrics_audit_for_app(journals)
    summary = metrics_summary(audit)

    cols = st.columns(5)
    cols[0].metric("Total journals", summary["total_journals"])
    cols[1].metric("With SJR", summary["with_sjr"])
    cols[2].metric("With h_index", summary["with_h_index"])
    cols[3].metric("With quartile", summary["with_quartile"])
    cols[4].metric("With OpenAlex", summary["with_openalex_source_id"])

    st.subheader("Missing Metrics")
    st.write(
        f"Missing SCImago: {summary['missing_scimago']}; "
        f"missing OpenAlex: {summary['missing_openalex']}; "
        f"missing or empty metric source files: {summary['missing_or_empty_sources']}."
    )
    st.dataframe(missing_metric_rows(audit), use_container_width=True)


def select_filter(label: str, values: list[str]) -> str:
    return st.selectbox(label, [""] + values, format_func=lambda value: value or "All")


if __name__ == "__main__":
    main()
