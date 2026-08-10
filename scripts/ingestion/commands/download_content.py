import json
from urllib.parse import urlparse

import fsspec
import markdownify
import requests
from bs4 import BeautifulSoup

from scripts.ingestion.commands.utils import (
    IngestionConfig,
    get_logger,
    slug_from_url,
)

_EXTENSION_BY_FORMAT = {"text": ".txt", "html": ".html", "markdown": ".md"}
_CONTENT_CANDIDATE_IDS = ("guide-contents", "content", "main-content")


def _html_to_output(html_bytes: bytes, output_format: str) -> str | None:
    """Extract the primary content element and render it in the target format.

    Returns None if neither #guide-contents nor #content is present.
    """
    soup = BeautifulSoup(html_bytes, features="html.parser")
    for candidate_id in _CONTENT_CANDIDATE_IDS:
        element = soup.find(id=candidate_id)
        if element is None:
            continue
        for noise in element(["script", "style", "nav", "aside", "footer", "header", "button", "form"]):
            noise.decompose()
        if output_format == "text":
            return element.get_text()
        raw_html = element.decode()
        if output_format == "markdown":
            return markdownify.markdownify(raw_html, heading_style="ATX", strip=["img"])
        return raw_html
    return None


def download_content(config: IngestionConfig):
    logger = get_logger()
    output_dir = config.output_dir_url
    fs, clean_output_dir = fsspec.core.url_to_fs(output_dir)
    sources: dict[str, str] = {}
    extension = _EXTENSION_BY_FORMAT.get(config.output_format, ".md")

    if config.links_list:
        links = config.links_list
    else:
        links_url = config.links_file_url
        links_fs, links_path = fsspec.core.url_to_fs(links_url)
        if links_fs.exists(links_path):
            with links_fs.open(links_path, "r") as file:
                links = [line.rstrip("\n") for line in file if line.strip()]
        else:
            logger.warning("A links input file has not been found. See README.md for more details")
            return

    output_file_count = 0
    link_skipped_count = 0

    if not links:
        logger.warning("No links to process. Check your links file.")
        logger.info(
            "📥 %d links processed, %d skipped — content stored in %s",
            output_file_count, link_skipped_count, output_dir,
        )
        return

    logger.info("🤖 Downloading and extracting content...")
    fs.makedirs(clean_output_dir, exist_ok=True)

    for count, link in enumerate(links, start=1):
        progress = f"({count}/{len(links)})"
        parsed = urlparse(link)

        if parsed.scheme != "https":
            logger.warning("%s %s — invalid URL (must use https)", progress, link)
            link_skipped_count += 1
            continue

        host = parsed.netloc
        if not host.endswith(".gov.uk"):
            logger.warning("%s %s — invalid URL (host must be *.gov.uk)", progress, link)
            link_skipped_count += 1
            continue

        slug = slug_from_url(link)
        if not slug:
            logger.warning("%s %s — could not derive slug from URL; skipping", progress, link)
            link_skipped_count += 1
            continue

        response = requests.get(link, timeout=30)
        if not response.ok:
            logger.error("%s %s — error (status code: %s)", progress, link, response.status_code)
            link_skipped_count += 1
            continue

        rendered = _html_to_output(response.content, config.output_format)
        if rendered is None:
            logger.warning(
                "%s %s — no extractable content (missing #%s)",
                progress, link, " or #".join(_CONTENT_CANDIDATE_IDS),
            )
            link_skipped_count += 1
            continue

        output_file_path = f"{clean_output_dir}/{slug}{extension}"
        with fs.open(output_file_path, "w", encoding="utf-8") as file:
            file.write(rendered)

        s3_key = f"{config.output_dir_url}/{slug}.md"
        sources[s3_key] = link
        output_file_count += 1
        logger.info("%s %s — stored as %s%s", progress, link, slug, extension)

    if sources:
        sources_url = f"{config.output_dir_url}/sources.json"
        sources_fs, sources_path = fsspec.core.url_to_fs(sources_url)
        parent = sources_fs._parent(sources_path)
        if parent:
            sources_fs.makedirs(parent, exist_ok=True)
        with sources_fs.open(sources_path, "w", encoding="utf-8") as file:
            json.dump(dict(sorted(sources.items())), file, indent=2)
        logger.info("🔗 Sources sidecar written: %s", sources_url)

    logger.info(
        "📥 %d links processed, %d skipped — content stored in %s",
        output_file_count, link_skipped_count, output_dir,
    )
