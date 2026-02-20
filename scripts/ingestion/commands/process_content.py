import os
from bs4 import BeautifulSoup
import pypandoc

Blue = "\033[34m"
Bold = "\033[1m"
Reset = "\033[0m"

def get_page_content_from_soup(soup, output_format):
    candidate_ids = ["guide-contents", "content"]

    for candidate_id in candidate_ids:
        content = soup.find(id=candidate_id)

        if content:
            if output_format == "text":
                return content.getText()
            elif output_format == "html" or output_format == "markdown":
                return content.decode()


def recursive_scan(path, file_list):
    for e in os.scandir(path):
        if e.is_dir():
            recursive_scan(e.path, file_list)
        if e.is_file():
            file_list.append(e)
    return file_list


def process_content(output_dir, input_dir, output_format):
    print("🤖 Processing content...")
    print("")
    skipped_input_files_count = 0
    output_files_count = 0

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    input_file_list = []
    input_file_list = recursive_scan(input_dir, input_file_list)

    for input_file in input_file_list:
        output_extension = ""

        if output_format == "text":
            output_extension = ".txt"
        elif output_format == "html":
            output_extension = ".html"
        elif output_format == "markdown":
            output_extension = ".md"

        output_file_path = input_file.path[len(input_dir)+1:].replace("/", "_").split(".")[0] + output_extension

        if os.path.exists(output_dir + "/" + output_file_path):
            print("❌  " + Blue + Bold + output_file_path + Reset +" (already exists)")
            skipped_input_files_count += 1
        else:
            with open(input_file.path, encoding="utf-8") as file:
                input_file_content = file.read()
                input_file_soup = BeautifulSoup(input_file_content, features="html.parser")

                output_file_content = get_page_content_from_soup(input_file_soup, output_format)

                if output_format == "markdown":
                    output_file_content = pypandoc.convert_text(output_file_content, format="html", to="gfm-raw_html")

                with open(output_dir + "/" + output_file_path, "w", encoding="utf-8") as output_file:
                    output_file.write(output_file_content)
                    output_file.close()
                print("✅ " + Blue + Bold + input_file.path[len(input_dir)+1:] + Reset)
                output_files_count += 1

    print("")
    print("📥 " + str(output_files_count) + " content files created")
    print("⏭️ " + str(skipped_input_files_count) + " input files skipped...")
    print("")
    print("Your content files are stored in " + Blue + Bold + output_dir + Reset)


