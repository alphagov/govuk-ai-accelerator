# 🛜 Ingestion

## Description

The ingestion steps are a set of scripts that can be run locally to gather gov.uk content based on a set of gov.uk links

## Getting Started

### Pre-requisites

- Python

### Setting Up

Create a list of links that you would like to ingest. Both CSV and text files are supported. See links.example.csv or links.example.txt for an example. Text files will be prioritised over CSV

The configuration can be changed in the config.ini:
- **output_dir** - The output directory for the final output content
- **output_format** - The final output format (html/text/markdown)
- **html_dir** - The output directory for the downloaded html files

### Running the Ingestion Process

The steps are ran from the command line.

1. Navigate to the directory in which the ingestion.py file exists
2. Run the ingestion process:
```bash
python ingestion.py all 
```


### Steps

The ingestion process is made up of steps which can be run separately:

#### 🪏 Download

The "download" step will go through each link in the links file and save the response as a html file. The default output directory is html_content.

```bash
python ingestion.py download 
```
#### ⚙️ Process

The "process" step will transform the raw html files into a set of files containing the relevant text content. The default output directory is output.

```bash
python ingestion.py process 
```

#### 🛀 Clean

The "clean" step will clean the data by doing the following:

- Reduce multiple new lines in a row to just one new line
- Remove any reference to printing the page (The print page is often used so that all sections for a page are included in a single link)

The files will remain the output directory 

```bash
python ingestion.py clean 
```

#### All 

All will run each step in order

```bash
python ingestion.py all 
```
