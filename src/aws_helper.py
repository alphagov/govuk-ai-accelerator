import io

import boto3

from scripts.ingestion.commands.utils import get_logger


def create_bucket_folder(bucket, folder):
    """Ensure a `.keep` placeholder exists at `s3://{bucket}/{folder}/.keep`.

    S3 has no real folders; writing the placeholder is idempotent, so we skip
    the existence check and always PUT.
    """
    try:
        log_buffer = io.StringIO()
        logger = get_logger(stream=log_buffer)
        boto3.client('s3').put_object(
            Bucket=bucket,
            Key=f"{folder}/.keep",
            Body=b'',
            ContentType='text/plain',
        )
        logger.info(f"Ensured folder '{folder}' in bucket '{bucket}'")
    except Exception as e:
        from flask import current_app
        current_app.logger.error(f"Error creating S3 folder: {str(e)}")