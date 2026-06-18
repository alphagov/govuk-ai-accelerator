"""Tests for the GET /ontology/domains page that IAs use to launch ingestion."""
import importlib
import sys

import pytest
from werkzeug.test import Client
from werkzeug.wrappers import Response


def _app_module():
    return importlib.import_module("govuk_ai_accelerator_app")


def _client():
    return Client(_app_module().create_app(), Response)


@pytest.fixture(autouse=True)
def _in_memory_db(monkeypatch):
    monkeypatch.setenv("ALLOW_IN_MEMORY_DB", "true")
    monkeypatch.setenv("DISABLE_TASK_MANAGER", "true")
    app_module = sys.modules.get("govuk_ai_accelerator_app")
    if app_module is not None:
        app_module._cached_app = None
    yield
    app_module = sys.modules.get("govuk_ai_accelerator_app")
    if app_module is not None:
        app_module._cached_app = None


def test_domains_page_renders_form():
    response = _client().get("/ontology/domains")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'name="domain"' in body
    assert 'id="urls-text"' in body


def test_header_links_to_create_domains_page():
    response = _client().get("/ontology/")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "/ontology/domains" in body
    assert "Create Domain" in body


def test_header_links_to_review_tests_after_create_domains():
    response = _client().get("/ontology/")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "/ontology/review-domains" in body
    assert "Review Domain" in body
    assert "/ontology/review-tests" in body
    assert "Review Tests" in body
    assert body.index("Create Ontology") < body.index("Review Ontology")
    assert body.index("Review Ontology") < body.index("Create Domain")
    assert body.index("Create Domain") < body.index("Review Domain")
    assert body.index("Review Domain") < body.index("Review Tests")
    assert "File Explorer" not in body
    assert "/viewer/bucket/govuk-ai-accelerator-data-integration" not in body


@pytest.mark.parametrize(
    "path",
    [
        "/ontology/review-ontologies",
        "/ontology/review-domains",
        "/ontology/review-tests",
    ],
)
def test_govuk_header_flush_to_viewport_without_materialize_reset(path):
    response = _client().get(path)

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    body_css = body.split("body {", 1)[1].split("}", 1)[0]
    assert "margin: 0;" in body_css
    assert "padding: 0;" in body_css


def test_review_domains_page_renders_govuk_review_table():
    response = _client().get("/ontology/review-domains")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "<title>Review Domains - GOV.UK Ontology Generator</title>" in body
    assert '<h1 class="govuk-heading-l">Review Domains</h1>' in body
    assert (
        "View your available domains below. Click any row to audit its source URLs."
        in body
    )
    assert 'id="domains-search"' in body
    assert '<table class="govuk-table review-domains-table" id="domains-table">' in body
    for heading in ("Domain Name", "Created At", "Status", "Notes"):
        assert f"<span>{heading}</span>" in body
    assert "/ontology/domains/review" in body
    assert "perPage = 10" in body
    assert "renderUrlPagination" in body
    assert "review-source-url-list" in body
    assert "editingSourceUrls: false" in body
    assert "edit-source-urls-action" in body
    assert "cancel-source-url-edit-action" in body
    assert "Save and rebuild domain" in body
    assert "renderDetailTab('source-urls', 'Source URLs')" in body
    assert "renderDetailTab('notes', 'Notes')" in body
    assert "review-note-action-link--secondary cancel-inline-note-action" in body
    assert "review-note-action-link--destructive delete-inline-note-action" in body
    assert "renderDomainActions(domain, notesLabel)" in body
    assert "review-row-actions" in body
    assert "delete-domain-action" in body
    assert "Delete domain" in body
    assert "review-domain-delete-confirmation" in body
    assert "This removes the domain from Review domains." in body
    assert "It does not delete historical jobs, notes, source URLs or files." in body
    assert "govuk-button govuk-button--warning confirm-delete-domain-action" in body
    assert "fetchJson(`/ontology/domains/review/${encodeURIComponent(jobId)}`" in body
    assert "method: 'DELETE'" in body
    assert "window.confirm" not in body
    assert "materialize.min.css" not in body
    assert "materialize.min.js" not in body
    assert "Material+Icons" not in body
    assert "material-icons" not in body
    assert body.index("Create Domain") < body.index("Review Tests")
    assert "File Explorer" not in body
    assert "/viewer/bucket/govuk-ai-accelerator-data-integration" not in body


def test_review_domains_detail_uses_vertical_tabs():
    response = _client().get("/ontology/review-domains")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert ".review-domain-detail {" in body
    assert "grid-template-columns: 280px minmax(0, 1fr);" in body
    assert "background: #ffffff;" in body
    assert ".review-detail-menu {" in body
    assert "background: #fafafa;" in body
    assert "border-right: 1px solid #e5e7eb;" in body
    assert "border-left: 4px solid transparent;" in body
    assert "border-bottom: 1px solid #e5e7eb;" in body
    assert "padding: 16px 18px;" in body
    assert ".review-detail-tab.is-active {" in body
    assert "border-left-color: #1d70b8;" in body
    assert "@media (max-width: 760px)" in body


def test_review_domains_detail_tabs_inherit_govuk_table_typography():
    response = _client().get("/ontology/review-domains")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    tab_css = body.split(".review-detail-tab {", 1)[1].split(
        ".review-detail-tab.is-active {", 1
    )[0]
    assert "font: inherit;" in tab_css


def test_review_domains_table_headers_match_review_table_typography():
    response = _client().get("/ontology/review-domains")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    sort_button_css = body.split(".review-sort-button {", 1)[1].split(
        ".review-sort-button:hover span:first-child {", 1
    )[0]
    assert "display: inline-flex;" in sort_button_css
    assert "align-items: center;" in sort_button_css
    assert "gap: 4px;" in sort_button_css
    assert "border-radius: 0;" in sort_button_css
    assert "font: inherit;" in sort_button_css


def test_review_domains_table_does_not_show_internal_job_ids():
    response = _client().get("/ontology/review-domains")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    first_cell_markup = body.split(
        '<strong class="govuk-!-font-weight-bold">${escapeHtml(domain.domain || \'-\')}</strong>',
        1,
    )[1].split("</td>", 1)[0]
    assert "domain.job_id" not in first_cell_markup
    assert "review-job-id" not in first_cell_markup
    assert "tr.dataset.jobId = domain.job_id;" in body


def test_review_domains_loads_source_urls_independently_from_notes():
    response = _client().get("/ontology/review-domains")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "loadSelectedDomainUrls(jobId)" in body
    assert "loadSelectedDomainNotes(jobId)" in body
    loader_markup = body.split("async function loadSelectedDomainData", 1)[1].split(
        "async function loadSelectedDomainUrls",
        1,
    )[0]
    assert "Promise.all([" not in loader_markup
    assert "Unable to load source URLs." in body
    assert "Retry source URLs" in body
