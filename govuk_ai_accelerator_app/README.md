# GOV.UK AI Accelerator 

This is a skeleton python app, in a subfolder, used to work through the CI pipelines

## Technical documentation

To be completed

### Before running the app (if applicable)

Local set up

    python3 -m venv .venv
    . .venv/bin/activate
    pip install -r requirements.txt


### Build

    docker build -t govuk-ai-accelerator .
    run -d -p 5000:5000 govuk-ai-accelerator


### Running the test suite

    pytest

### Further documentation

To be completed

## Licence

Link to your LICENCE file.

[MIT LICENCE](LICENCE)