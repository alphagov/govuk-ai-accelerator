import logging

import boto3

logger = logging.getLogger(__name__)


def create_bucket_folder(bucket, folder):
    """Ensure a `.keep` placeholder exists at `s3://{bucket}/{folder}/.keep`.

    S3 has no real folders; writing the placeholder is idempotent, so we skip
    the existence check and always PUT.
    """
    boto3.client('s3').put_object(
        Bucket=bucket,
        Key=f"{folder}/.keep",
        Body=b'',
        ContentType='text/plain',
    )
    logger.info("Ensured folder '%s' in bucket '%s'", folder, bucket)
