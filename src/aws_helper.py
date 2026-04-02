import io

import boto3

from scripts.ingestion.commands.utils import get_logger


def create_bucket_folder(bucket, folder):
    """
    Creates a folder-like structure in an AWS S3 bucket if it doesn't already exist.
    Since S3 doesn't have true folders, this function simulates folder creation by:
    1. Checking if any objects exist with the specified folder prefix
    2. Creating a placeholder file (.keep) if no objects are found
    
    Args:
        bucket (str): The name of the S3 bucket where the folder should be created
        folder (str): The name of the folder to create (without a trailing slash)
    Raises:
        Exception: If there's an error accessing S3 or creating the folder structure
    """
    try:
        log_buffer = io.StringIO()
        logger = get_logger(stream=log_buffer)
        s3_client = boto3.client('s3')

        response = s3_client.list_objects_v2(
            Bucket=bucket,
            Prefix=f"{folder}/",
            MaxKeys=1
        )

        if 'Contents' not in response:
            # Create a placeholder file to simulate folder creation
            s3_client.put_object(
                Bucket=bucket,
                Key=f"{folder}/.keep",
                Body=b'',
                ContentType='text/plain'
            )
            logger.info(f"Created folder '{folder}' in bucket '{bucket}'")
        else:
            logger.info(f"Folder '{folder}' already exists in bucket '{bucket}'")

    except Exception as e:
        from flask import current_app
        current_app.logger.error(f"Error checking/creating S3 folder: {str(e)}")