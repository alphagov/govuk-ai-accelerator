# GOV.UK AI Accelerator 

This is a skeleton python app, in a subfolder, used to work through the CI pipelines

## Technical documentation

To be completed

### Before running the app (if applicable)

#### Database

this is a very simple local database to test code setup, connectivity etc. Not to be used in prod.
The /test url will expect there to be a test table, with at least one row. the url will then be able to be used
to validate the environment.

Once the app is in active developement this should be removed and replaced.

Connect to local postgres instance and run:

    CREATE database "govuk_ai_accelerator";
    CREATE USER "govuk_ai_accelerator_user" WITH PASSWORD '__set a password__';
    GRANT ALL PRIVILEGES ON DATABASE "govuk_ai_accelerator" to "govuk_ai_accelerator_user";
    GRANT ALL ON SCHEMA public TO "govuk_ai_accelerator_user";
    # quit as admin user
    psql -h localhost -U govuk_ai_accelerator_user govuk_ai_accelerator
    create table TEST (info varchar(255));
    insert into TEST values ('123');


#### Local set up
    source environment.sh
    export DATABASE_PASSWORD=__add a pasword__
    python3 -m venv .venv
    . .venv/bin/activate
    pip install -r requirements.txt


#### Local run

With server

    waitress-serve --port 3000 --call 'govuk_ai_accelerator_app:create_app'

Debug mode

     flask --app govuk_ai_accelerator_app.py run

### Build

With Docker

    docker build -t govuk-ai-accelerator .
    docker run -d -p 3000:3000 govuk-ai-accelerator

### Running the test suite

    pytest

### Further documentation

To be completed

## Licence

Link to your LICENCE file.

[MIT LICENCE](LICENCE)