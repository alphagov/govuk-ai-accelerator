# 🛜 Ingestion

## Description

The ingestion steps are a set of scripts that can be run locally to gather gov.uk content based on a set of gov.uk links

## Getting Started

### Pre-requisites

- Python

### Setting Up

Create a list of links that you would like to ingest. This file should be called links.txt. See links.example.txt for an example.

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

The Download step will go through each link in the links file and save the response as a html file. The default output directory is html_content.

```bash
python ingestion.py download 
```
#### ⚙️ Process

The Process step will transform the raw html files into a set of files containing the relevant text content. The default output directory is output.

```bash
python ingestion.py process 
```
#### All 

All will run each step in order

```bash
python ingestion.py all 
```
