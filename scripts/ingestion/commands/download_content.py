import os
import requests
from urllib.parse import urlparse
import fsspec

from scripts.pipeline.logging_config import logger


def download_content(html_output_dir: str, links, config):
    fs, clean_html_dir = fsspec.core.url_to_fs(html_output_dir)

    if isinstance(links, list):
        pass
    else:
        links_fs, links_path = fsspec.core.url_to_fs(links)
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

            url_path = urlparse(link).path
            clean_output_file = clean_html_dir + url_path + ".html"

            if fs.exists(clean_output_file):
                logger.info("%s %s — skipped (already exists)", progress, link)
                link_skipped_count += 1
                continue
            else:
                response = requests.get(link, timeout=30)

                if not response.ok:
                    logger.error("%s %s — error (status code: %s)", progress, link, response.status_code)
                    link_skipped_count += 1
                    continue

                fs.makedirs(fs._parent(clean_output_file), exist_ok=True)

                with fs.open(clean_output_file, 'wb') as file:
                    file.write(response.content)

                output_file_count += 1
                logger.info("%s %s — downloaded", progress, link)
    else:
        logger.warning("No links to process. Check your links file.")

    logger.info("📥 %d links processed, %d skipped — html files stored in %s",
                output_file_count, link_skipped_count, html_output_dir)