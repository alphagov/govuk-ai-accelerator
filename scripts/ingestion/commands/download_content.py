import json
import requests
from urllib.parse import urlparse
import fsspec

from scripts.ingestion.commands.utils import get_logger, IngestionConfig, slug_from_url

def download_content(config: IngestionConfig):
    logger = get_logger()
    html_output_dir = config.html_dir_url

    fs, clean_html_dir = fsspec.core.url_to_fs(html_output_dir)
    sources: dict[str, str] = {}

    if config.links_list:
        links = config.links_list
    else:
        links_url = config.links_file_url
        links_fs, links_path = fsspec.core.url_to_fs(links_url)
        if links_fs.exists(links_path):
            with links_fs.open(links_path, 'r') as file:
                links = [line.rstrip('\n') for line in file if line.strip()]
        else:
            logger.warning("A links input file has not been found. See README.md for more details")
            return

    output_file_count = 0
    link_skipped_count = 0

    if links:
        logger.info("🤖 Downloading content...")
        count = 0
        for link in links:
            count += 1
            progress = f"({count}/{len(links)})"

            if urlparse(link).scheme != "https":
                logger.warning("%s %s — invalid URL (must use https)", progress, link)
                link_skipped_count += 1
                continue

            if urlparse(link).netloc != "www.gov.uk":
                logger.warning("%s %s — invalid URL (must have www.gov.uk host)", progress, link)
                link_skipped_count += 1
                continue

            if urlparse(link).path.split('/')[-1] != "print":
                logger.warning("%s %s — invalid URL (the Ingestion Process only supports printable pages at this time e.g. www.gov.uk/example/print)", progress, link)
                link_skipped_count += 1
                continue

            slug = slug_from_url(link)
            if not slug:
                logger.warning("%s %s — could not derive slug from URL; skipping", progress, link)
                link_skipped_count += 1
                continue

            clean_output_file = f"{clean_html_dir}/{slug}.html"

            response = requests.get(link, timeout=30)

            if not response.ok:
                logger.error("%s %s — error (status code: %s)", progress, link, response.status_code)
                link_skipped_count += 1
                continue

            fs.makedirs(clean_html_dir, exist_ok=True)

            with fs.open(clean_output_file, 'wb') as file:
                file.write(response.content)

            sources[slug] = link
            output_file_count += 1
            logger.info("%s %s — downloaded", progress, link)
    else:
        logger.warning("No links to process. Check your links file.")

    if sources:
        sources_url = f"{config.output_dir_url}/sources.json"
        sources_fs, sources_path = fsspec.core.url_to_fs(sources_url)
        parent = sources_fs._parent(sources_path)
        if parent:
            sources_fs.makedirs(parent, exist_ok=True)
        with sources_fs.open(sources_path, 'w', encoding='utf-8') as file:
            json.dump(dict(sorted(sources.items())), file, indent=2)
        logger.info("🔗 Sources sidecar written: %s", sources_url)

    logger.info("📥 %d links processed, %d skipped — html files stored in %s",
                output_file_count, link_skipped_count, html_output_dir)