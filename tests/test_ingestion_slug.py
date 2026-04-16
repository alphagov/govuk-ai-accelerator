"""Tests for slug_from_url — flat filename derivation for ingested pages."""
import pytest

from scripts.ingestion.commands.utils import slug_from_url


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://www.gov.uk/foreign-travel-advice/print", "foreign-travel-advice"),
        (
            "https://www.gov.uk/government/publications/visa/print",
            "government-publications-visa",
        ),
        ("https://www.gov.uk/foreign-travel-advice/print/", "foreign-travel-advice"),
        ("https://www.gov.uk/get-document-legalised/print", "get-document-legalised"),
    ],
)
def test_slug_from_url_strips_print_and_flattens(url, expected):
    assert slug_from_url(url) == expected


def test_slug_from_url_bare_print_returns_empty_string():
    assert slug_from_url("https://www.gov.uk/print") == ""
