# testing bedrock connection

import boto3
import json
import os



def funfact(greetings):
    try:

        bedrock_runtime = boto3.client(service_name='bedrock-runtime')
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
        sentence = f'''
        Greetings {greetings}
        Heres the fact for today :)
        {space_facts}
        '''
            
    except Exception as e:
        print(f"Error invoking model: {e}")

