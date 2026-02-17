import os
import requests
from urllib.parse import urlparse

Blue = "\033[34m"
Bold = "\033[1m"
Reset = "\033[0m"

def download_content(html_output_dir, file_extension):
    if os.path.exists("links.txt"):
        with open("links.txt", 'r') as file:
            links = [line.rstrip('\n') for line in file]

    else:
        print("⚠️ links.txt not found. Please see links.example.txt for an example")
        return

    output_file_count = 0
    link_skipped_count = 0

    if links:
        print("🤖 Downloading content...")
        for link in links:
            url_path = urlparse(link).path

            if os.path.exists(html_output_dir + url_path + file_extension):
                print("❌ "+ Blue + Bold + link + Reset + " (already exists)")
                link_skipped_count += 1
            else:
                response = requests.get(link)

                output_file_path = html_output_dir + url_path + file_extension

                os.makedirs(os.path.dirname(output_file_path), exist_ok=True)

                with open(output_file_path, 'wb') as file:
                    file.write(response.content)

                output_file_count += 1

                print("✅ " + Blue + Bold + link + Reset)
    else:
        print("⚠️ The links.txt does not contain any links. Please see links.example.txt for an example")

    print("")
    print("📥 " + str(output_file_count) + " links processed")
    print("⏭️ " + str(link_skipped_count) + " links skipped...")
    print("")
    print("Your html files are stored in " + Blue + Bold + html_output_dir + Reset)