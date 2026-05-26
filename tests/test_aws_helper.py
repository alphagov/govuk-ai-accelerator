import io
import logging

import pytest

from scripts.ingestion.commands.utils import get_logger
from src.aws_helper import create_bucket_folder


@pytest.fixture(autouse=True)
def _reset_ingestion_logger():
    logger = logging.getLogger("ontology-ingestion")
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    yield
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)


def test_create_bucket_folder_does_not_reconfigure_ingestion_logger(monkeypatch):
    class FakeS3Client:
        def put_object(self, **kwargs):
            self.kwargs = kwargs

    fake_client = FakeS3Client()
    monkeypatch.setattr("src.aws_helper.boto3.client", lambda service_name: fake_client)

    ingestion_log_stream = io.StringIO()
    ingestion_logger = get_logger(stream=ingestion_log_stream)
    original_handlers = list(ingestion_logger.handlers)

    create_bucket_folder("test-bucket", "visa")

    assert ingestion_logger.handlers == original_handlers
    assert "Ensured folder" not in ingestion_log_stream.getvalue()
    assert fake_client.kwargs == {
        "Bucket": "test-bucket",
        "Key": "visa/.keep",
        "Body": b"",
        "ContentType": "text/plain",
    }
