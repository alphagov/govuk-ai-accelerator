import os
import fsspec

from scripts.pipeline.logging_config import logger


def clean_content(output_dir, config):
    logger.info("🛀 Cleaning content...")

    files_cleaned = 0

    fs, clean_output_dir = fsspec.core.url_to_fs(output_dir)
    output_files = [f for f in fs.find(clean_output_dir, detail=False) if not fs.isdir(f)]

    if output_files:
        count = 0
        for file_path in output_files:
            count += 1
            file = os.path.basename(file_path)
            progress = f"({count}/{len(output_files)})"

            with fs.open(file_path, 'r') as content:
                lines = content.readlines()

            new_lines = []
            previous_line_blank = False

            for line in lines:
                new_line = line.strip()

                if new_line in {"Print this page", "Printable version"}:
                    continue

                if new_line == "":
                    if not previous_line_blank:
                        new_lines.append(line)
                    previous_line_blank = True
                else:
                    new_lines.append(line.lstrip())
                    previous_line_blank = False

            with fs.open(file_path, 'w') as content:
                content.writelines(new_lines)
            logger.info("%s %s — cleaned", progress, file)
            files_cleaned += 1

        logger.info("🧼 %d files cleaned", files_cleaned)
    else:
        logger.warning("No content files found in %s. Check the output directory.", output_dir)