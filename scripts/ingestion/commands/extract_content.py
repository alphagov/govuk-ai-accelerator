import os

from bs4 import BeautifulSoup
import pypandoc
import fsspec

from scripts.ingestion.commands.utils import get_logger, IngestionConfig

def create_string_from_list(items):
    if len(items) > 1:
        formatted_string = ", ".join(items[:-1]) + " and " + items[-1]
    else:
        formatted_string = "".join(items)

    return formatted_string

def get_page_content_from_soup(soup, output_format, logger, progress, input_file):
    candidate_ids = ["guide-contents", "content"]

    for candidate_id in candidate_ids:
        content = soup.find(id=candidate_id)

        if content:
            if output_format == "text":
                return content.getText()
            elif output_format == "html" or output_format == "markdown":
                return content.decode()
        else:
            logger.warning("%s %s — Unsupported content (required ID not found. Ensure the HTML contains a tag with a specified ID - %s)", progress, input_file, create_string_from_list(candidate_ids))

def recursive_scan(path):
    fs, root_path = fsspec.core.url_to_fs(path)
    return fs.find(root_path)



def extract_content(config: IngestionConfig):
    logger = get_logger()
    logger.info("🤖 Extracting content...")
    
    output_dir = config.output_dir_url
    input_dir = config.html_dir_url

    skipped_input_files_count = 0
    output_files_count = 0

    out_fs, clean_output_dir = fsspec.core.url_to_fs(output_dir)
    in_fs, clean_input_dir = fsspec.core.url_to_fs(input_dir)

    input_file_list = [
        f for f in in_fs.find(clean_input_dir)
        if f.rstrip('/') != clean_input_dir.rstrip('/') and not in_fs.isdir(f)
    ]

    extension_by_format = {"text": ".txt", "html": ".html", "markdown": ".md"}
    output_extension = extension_by_format.get(config.output_format, "")

    out_fs.makedirs(clean_output_dir, exist_ok=True)

    for count, input_file in enumerate(input_file_list, start=1):
        progress = f"({count}/{len(input_file_list)})"

        slug = os.path.splitext(os.path.basename(input_file))[0]
        output_file_path = slug + output_extension
        full_output_path = f"{clean_output_dir}/{output_file_path}"

        with in_fs.open(input_file, 'rb') as file:
            input_file_soup = BeautifulSoup(file.read(), features="html.parser")

        output_file_content = get_page_content_from_soup(
            input_file_soup, config.output_format, logger, progress, input_file
        )

        if output_file_content is None:
            logger.warning("%s %s — no extractable content found in [%s], skipping",
                           progress, output_file_path, config.output_format)
            skipped_input_files_count += 1
            continue

        if config.output_format == "markdown":
            output_file_content = pypandoc.convert_text(output_file_content, format="html", to="gfm-raw_html")

        with out_fs.open(full_output_path, "w", encoding="utf-8") as output_file:
            output_file.write(output_file_content)
        logger.info("%s %s — extracted", progress, output_file_path)
        output_files_count += 1

    logger.info("📥 %d files created, %d skipped — content stored in %s",
                output_files_count, skipped_input_files_count, output_dir)
