from taxonomy_ontology_accelerator.commons.utils.logger import get_logger
from typing import cast
import boto3
import json
import os
import time



from dotenv import load_dotenv

load_dotenv()
logger = cast('Richlogger', get_logger())

def llm_fact():
    try:   
    

        bedrock_runtime = boto3.client(service_name='bedrock-runtime', region_name= 'eu-west-1')
        model_id = 'eu.anthropic.claude-3-7-sonnet-20250219-v1:0'
        prompt = "Hello! Please give me a short, one-sentence interesting fact about space."
        body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 512,
            "messages": [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": prompt}]
                }
            ],
            "temperature": 0.5,
            "top_p": 0.9
        })
        
        response = bedrock_runtime.invoke_model( body=body, modelId=model_id, accept='application/json', contentType='application/json')
        response_body = json.loads(response.get('body').read())
        space_facts = response_body.get('content')[0].get('text')
        sentence = f'''{space_facts}'''
        return sentence
            
    except Exception as e:
        return f"Error invoking model: {e}"




def run_counter(count_value: int)-> bool:
    time_start = time.perf_counter()
    if isinstance(count_value, int): 

        for i in range(count_value): 
            logger.info(f'current count {i}')    
        time_end = time.perf_counter()

        return f"Task completed in {time_end - time_start :.4f}s"
    else:
        raise Exception(f'Value {count_value} must be an int')

    
def counter_call_back(future):

    try:
        results = future.result()
        logger.info('Task done')
        return results
    except:
        return 'Error occurred when processing'


def list_s3_directories(bucket_name, prefix=''):
    s3_client = boto3.client('s3')
    
    if prefix and not prefix.endswith('/'):
        prefix += '/'

    response = s3_client.list_objects_v2(
        Bucket=bucket_name,
        Prefix=prefix,
        Delimiter='/'
    )
    return response
