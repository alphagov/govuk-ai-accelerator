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
    - AWS credentials are available in the environment

    ````
    #using brew
    brew install uv

    #using pip
    pip install uv
    ````

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

Use the following endpoints to verify the worker's core functionality. Ensure your local environment is running at `http://localhost`.

---

### 1. LLM Integration (Amazon Bedrock)
**Endpoint:** `GET /worker/llm`  
**Description:** Validates the connection to Amazon Bedrock and the LLM's generative capabilities.

> **Expected Behavior:** Returns a JSON response containing a randomly generated fact about space.

---

### 2. Asynchronous Background Tasks
**Endpoint:** `GET /worker/test?no=<int>`  
**Example:** `http://localhost/worker/test?no=10000`  
**Description:** Verifies that the worker can handle long-running background processes without triggering a request timeout.

> **Expected Behavior:** Initiates a timer/counter based on the provided digit.

---

### 3. AWS S3 Connectivity
**Endpoint:** `GET /worker/list?bucket=<bucket_name>`  
**Example:** `http://localhost/worker/list?bucket=abc_folder`  
**Description:** Tests the worker’s IAM permissions and connectivity to specific S3 buckets.

> **Expected Behavior:** Returns a list of objects folders residing in the specified S3 bucket.



### Running the test suite

    pytest

### Further documentation

To be completed

## Licence

Link to your LICENCE file.

[MIT LICENCE](LICENCE)




