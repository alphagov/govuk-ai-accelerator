# GOV.UK AI Accelerator 

This is a skeleton python app, in a subfolder, used to work through the CI pipelines

## Technical documentation

To be completed

### Before running the app (if applicable)

#### Database

this is a very simple local database to test code setup, connectivity etc. Not to be used in prod.
The root url (http://localhost:3000/) will expect there to be a test table, with at least one row. this url will then be able to be used
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
    pre-req: 
    - ensure you have uv installed 
    ````
    #using brew
    brew install uv

    #using pip
    pip install uv
    ````
    - AWS credentials are available in the environment


    source environment.sh
    uv init --python 3.13
    uv python pin 3.13   #ensures it aligns with accelerator version
    uv add -r requirements.txt
    uv add "git+ssh://git@github.com/alphagov/govuk-ai-accelerator-tw-accelerator.git"

#### Local run

With server

    uv run waitress-serve --port 5000 --call 'govuk_ai_accelerator_app:create_app'

Debug mode
    uv run govuk_ai_accelerator_app.py 



### Build

With Docker
    # to run locally
    # uncomment  line 6 and line 25 ## NOTE:: Remember only use this for local development
    # comment out  line 5 and line 27 -30

    docker build --build-arg GITHUB_TOKEN=<your gh token> -t app_name .
    docker run -p 3000:3000 \
    -e AWS_REGION \
    -e AWS_DEFAULT_REGION \
    -e AWS_ACCESS_KEY_ID \
    -e AWS_SECRET_ACCESS_KEY \
    -e AWS_SESSION_TOKEN \
    app_name

## API Testing & Verification

The application provides REST endpoints for ontology processing with asynchronous job tracking. Ensure your local environment is running at `http://localhost:5000`.

---

### 1. Health Check
**Endpoint:** `GET /healthcheck/ready`  
**Description:** Validates that the application is running and healthy.

> **Expected Behavior:** Returns status 200 with JSON response: `{"status": "healthy", "message": "Application is ready"}`

---

### 2. Ontology UI
**Endpoint:** `GET /ontology/`  
**Description:** Loads the web interface for submitting ontology processing jobs.

> **Expected Behavior:** Returns HTML form for uploading configuration YAML and domain prompt text files.

---

### 3. Submit Ontology Job
**Endpoint:** `POST /ontology/submit`  
**Description:** Submits a configuration file and optional domain prompt for asynchronous ontology processing. Returns immediately with a job ID for status polling.

**Request:**
- Form data with:
  - `file`: Configuration YAML file (required)
  - `text_file`: Domain prompt text file (optional)

**Example:**
```bash
curl -X POST http://localhost:5000/ontology/submit \
  -F "file=@config.yaml" \
  -F "text_file=@domain_prompt.txt"
```

> **Expected Behavior:** Returns status 202 (Accepted) with JSON: `{"job_id": "<uuid>", "status": "pending"}`

---

### 4. Check Job Status
**Endpoint:** `GET /ontology/status/<job_id>`  
**Example:** `http://localhost:5000/ontology/status/550e8400-e29b-41d4-a716-446655440000`  
**Description:** Polls the status of a previously submitted ontology processing job.

> **Expected Behavior:** Returns status 200 with JSON: `{"job_id": "<uuid>", "status": "<pending|completed|failed>"}`



### Running the test suite

    pytest

### Further documentation

To be completed

## Licence

Link to your LICENCE file.

[MIT LICENCE](LICENCE)




