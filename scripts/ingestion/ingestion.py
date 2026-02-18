import argparse

from commands.process_content import process_content
from commands.download_content import download_content
from commands.clean_content import clean_content

html_output_dir = "html_content"
file_extension = ".html"

output_dir = "output"
input_dir = "html_content"
output_format = "TEXT"

parser = argparse.ArgumentParser(prog='ingestion', description='Scrapes a list of links and processes them to generate content files')
parser.add_argument('stage', type=str, help='The stage of the ingestion to run. This can be "scrape", "process", or "all"')

args = parser.parse_args()

if args.stage == 'download':
    download_content(html_output_dir, file_extension)
if args.stage == 'process':
    process_content(output_dir, input_dir, output_format)
if args.stage == 'clean':
    clean_content(output_dir)
if args.stage == 'all':
    download_content(html_output_dir, file_extension)
    print("")
    process_content(output_dir, html_output_dir, output_format)
    print("")
    clean_content(output_dir)

print('')
print('🎉 Completed Successfully')