import argparse

from commands.extract_content import extract_content
from commands.download_content import download_content
from commands.clean_content import clean_content

import configparser

config = configparser.ConfigParser()
config.read("config.ini")

html_dir = config["general"]["html_dir"] or "html_content"
output_dir = config["general"]["output_dir"] or "output"
output_format =  config["general"]["output_format"] or "markdown"
links_file = config["general"]["links_file"] or "links.txt" 

parser = argparse.ArgumentParser(prog='ingestion', description='Scrapes a list of links and processes them to generate content files')
parser.add_argument('stage', type=str, help='The stage of the ingestion to run. This can be "scrape", "extract", "clean", or "all"')

args = parser.parse_args()

if args.stage == 'download':
    download_content(html_dir, links_file, config)
if args.stage == 'extract':
    extract_content(output_dir, html_dir, output_format, config)
if args.stage == 'clean':
    clean_content(output_dir, config)
if args.stage == 'all':
    download_content(html_dir, links_file, config) 
    print("")
    extract_content(output_dir, html_dir, output_format, config)
    print("")
    clean_content(output_dir, config)

print('')
print('🎉 Completed Successfully')