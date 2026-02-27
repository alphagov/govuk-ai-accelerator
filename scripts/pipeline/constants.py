APP_HOST = '0.0.0.0'
APP_PORT = 3000

YAML_EXTENSIONS = ('.yaml', '.yml')

AWS_REGION = 'eu-west-1'
BEDROCK_MODEL_ID = 'eu.anthropic.claude-3-7-sonnet-20250219-v1:0'

EXECUTOR_MAX_WORKERS = 4

BLUEPRINTS = {
    'healthcheck': {'prefix': '/healthcheck'},
    'ontology': {'prefix': '/ontology'},
}

__all__ = [
    'APP_HOST',
    'APP_PORT',
    'YAML_EXTENSIONS',
    'AWS_REGION',
    'BEDROCK_MODEL_ID',
    'EXECUTOR_MAX_WORKERS',
    'BLUEPRINTS',
]
