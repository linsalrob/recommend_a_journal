"""Pure helpers for Streamlit manuscript upload workflows."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from journal_recommender.document_extract import ExtractedManuscript
from journal_recommender.feature_drafting import (
    draft_features_from_extracted,
    extract_and_draft_features,
    manuscript_features_to_yaml,
)
from journal_recommender.manuscript import ManuscriptFeatures


@dataclass
class ManuscriptUploadDraft:
    extracted: ExtractedManuscript
    features: ManuscriptFeatures
    yaml_text: str


def prepare_uploaded_manuscript(
    filename: str,
    raw_bytes: bytes,
) -> ManuscriptUploadDraft:
    extracted, features = extract_and_draft_features(
        Path(filename), raw_bytes=raw_bytes
    )
    return ManuscriptUploadDraft(
        extracted=extracted,
        features=features,
        yaml_text=manuscript_features_to_yaml(features),
    )


def prepare_extracted_manuscript(
    extracted: ExtractedManuscript,
) -> ManuscriptUploadDraft:
    features = draft_features_from_extracted(extracted)
    return ManuscriptUploadDraft(
        extracted=extracted,
        features=features,
        yaml_text=manuscript_features_to_yaml(features),
    )
