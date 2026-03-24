import os

from bs4 import BeautifulSoup
import pypandoc
import fsspec

from scripts.ingestion.commands.utils import get_logger, IngestionConfig


def get_page_content_from_soup(soup, output_format):
    candidate_ids = ["guide-contents", "content"]

    for candidate_id in candidate_ids:
        content = soup.find(id=candidate_id)

        if content:
            if output_format == "text":
                return content.getText()
            elif output_format == "html" or output_format == "markdown":
                return content.decode()
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
    if not clean_input_dir.endswith('/'):
        clean_input_dir += '/'

    input_file_list = [f for f in in_fs.find(clean_input_dir) if f.rstrip('/') != clean_input_dir.rstrip('/')]

    count = 0
    for input_file in input_file_list:
        if in_fs.isdir(input_file):
            continue

        count += 1
        progress = f"({count}/{len(input_file_list)})"

        output_extension = ""

        if config.output_format == "text":
            output_extension = ".txt"
        elif config.output_format == "html":
            output_extension = ".html"
        elif config.output_format == "markdown":
            output_extension = ".md"

        if input_file.startswith(clean_input_dir):
            rel_path = input_file[len(clean_input_dir):].lstrip('/')
        else:
            rel_path = input_file
        output_file_path = os.path.splitext(rel_path)[0] + output_extension
        full_output_path = clean_output_dir + "/" + output_file_path

        if out_fs.exists(full_output_path):
            logger.info("%s %s — skipped (already exists)", progress, output_file_path)
            skipped_input_files_count += 1
        else:
            with in_fs.open(input_file, 'rb') as file:
                input_file_content = file.read()
                input_file_soup = BeautifulSoup(input_file_content, features="html.parser")

                output_file_content = get_page_content_from_soup(input_file_soup, config.output_format)

                if output_file_content is None:
                    logger.warning("%s %s — no extractable content found in [%s], skipping", progress, rel_path, config.output_format)
                    skipped_input_files_count += 1
                    continue

                if config.output_format == "markdown":
                    output_file_content = pypandoc.convert_text(output_file_content, format="html", to="gfm-raw_html")

                parent_dir = clean_output_dir + "/" + os.path.dirname(output_file_path)
                out_fs.makedirs(parent_dir, exist_ok=True)
                with out_fs.open(full_output_path, "w", encoding="utf-8") as output_file:
                    output_file.write(output_file_content)
                logger.info("%s %s — extracted", progress, output_file_path)
                output_files_count += 1

    logger.info("📥 %d files created, %d skipped — content stored in %s",
                output_files_count, skipped_input_files_count, output_dir)
