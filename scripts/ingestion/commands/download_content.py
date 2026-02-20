import csv
import os
import requests
from urllib.parse import urlparse

Cyan = '\033[96m'
Blue = "\033[34m"
Bold = "\033[1m"
Reset = "\033[0m"

def download_content(html_output_dir):
    if os.path.exists("links.txt"):
        with open("links.txt", 'r') as file:
            links = [line.rstrip('\n') for line in file]
    elif os.path.exists("links.csv"):
        with open("links.csv", 'r') as file:
            csv_file = csv.reader(file)
            links = [line[0] for line in csv_file]
    else:
        print("⚠️ A links input file has not been found. See README.md for more details")
        return

    output_file_count = 0
    link_skipped_count = 0

    if links:
        print(Bold + Cyan + "🤖 Downloading content..." + Reset)
        print("")
        count = 0
        for link in links:
            count += 1
            progress = " (" + str(count) + "/" + str(len(links)) + ") "

            if urlparse(link).scheme != "https":
                print("❌" + progress + Blue + Bold + link + Reset + " (Invalid URl - ensure that the URL uses https)")
                link_skipped_count += 1
                continue

            if urlparse(link).netloc != "www.gov.uk":
                print("❌" + progress + Blue + Bold + link + Reset + " (Invalid URl - ensure that the URL has the 'www.gov.uk' host)")
                link_skipped_count += 1
                continue

            url_path = urlparse(link).path

            if os.path.exists(html_output_dir + url_path + ".html"):
                print("❌" + progress + Blue + Bold + link + Reset + " (already exists)")
                link_skipped_count += 1
                continue
            else:
                response = requests.get(link)

                if not response.ok:
                    print("❌" + progress + Blue + Bold + link + Reset + " (Error - status code: " + str(response.status_code) + ")")
                    link_skipped_count += 1
                    continue

                output_file_path = html_output_dir + url_path + ".html"

                os.makedirs(os.path.dirname(output_file_path), exist_ok=True)

                with open(output_file_path, 'wb') as file:
                    file.write(response.content)

                output_file_count += 1

                print("✅" + progress + Blue + Bold + link + Reset)
    else:
        print("⚠️ The links.txt does not contain any links. Please see links.example.txt for an example")

    print("")
    print("📥 " + str(output_file_count) + " links processed")
    print("⏭️ " + str(link_skipped_count) + " links skipped...")
    print("")
    print("Your html files are stored in " + Blue + Bold + html_output_dir + Reset)