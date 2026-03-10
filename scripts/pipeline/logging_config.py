import logging
from typing import Any, cast

try:
    from taxonomy_ontology_accelerator.commons.utils.logger import get_logger
except ModuleNotFoundError:
    def get_logger() -> logging.Logger:
        logger = logging.getLogger("govuk-ai-accelerator")
        if not logger.handlers:
            logging.basicConfig(level=logging.INFO)
        return logger


logger = cast(Any, get_logger())

__all__ = ['logger']
