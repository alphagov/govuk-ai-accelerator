import os

from bs4 import BeautifulSoup
import pypandoc
import fsspec

from scripts.pipeline.logging_config import logger


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


def extract_content(output_dir, input_dir, output_format, config):
    logger.info("🤖 Extracting content...")
    
    protocol = config.get("general", "protocol", fallback="local")
    if protocol == "local": protocol = "file"
    
    if "://" not in output_dir: output_dir = f"{protocol}://{output_dir}"
    if "://" not in input_dir: input_dir = f"{protocol}://{input_dir}"

    skipped_input_files_count = 0
    output_files_count = 0

    out_fs, clean_output_dir = fsspec.core.url_to_fs(output_dir)
    in_fs, clean_input_dir = fsspec.core.url_to_fs(input_dir)

    if not out_fs.exists(clean_output_dir):
        out_fs.makedirs(clean_output_dir)

    input_file_list = in_fs.find(clean_input_dir)

    count = 0
    for input_file in input_file_list:
        count += 1
        progress = f"({count}/{len(input_file_list)})"

        output_extension = ""

        if output_format == "text":
            output_extension = ".txt"
        elif output_format == "html":
            output_extension = ".html"
        elif output_format == "markdown":
            output_extension = ".md"

        rel_path = input_file[len(clean_input_dir) + 1:]
        output_file_path = os.path.splitext(rel_path)[0] + output_extension
        full_output_path = clean_output_dir + "/" + output_file_path

        if out_fs.exists(full_output_path):
            logger.info("%s %s — skipped (already exists)", progress, output_file_path)
            skipped_input_files_count += 1
        else:
            with in_fs.open(input_file, encoding="utf-8") as file:
                input_file_content = file.read()
                input_file_soup = BeautifulSoup(input_file_content, features="html.parser")

                output_file_content = get_page_content_from_soup(input_file_soup, output_format)

                if output_file_content is None:
                    logger.warning("%s %s — no extractable content, skipping", progress, rel_path)
                    skipped_input_files_count += 1
                    continue

                if output_format == "markdown":
                    output_file_content = pypandoc.convert_text(output_file_content, format="html", to="gfm-raw_html")

                parent_dir = clean_output_dir + "/" + os.path.dirname(output_file_path)
                out_fs.makedirs(parent_dir, exist_ok=True)
                with out_fs.open(full_output_path, "w", encoding="utf-8") as output_file:
                    output_file.write(output_file_content)
                logger.info("%s %s — extracted", progress, output_file_path)
                output_files_count += 1

    logger.info("📥 %d files created, %d skipped — content stored in %s",
                output_files_count, skipped_input_files_count, output_dir)
