from pathlib import Path

import logging

from finrag.utils import load_env_file, check_required_env_vars


logger = logging.getLogger(__name__)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logger.info("Project root: %s", Path(__file__).parent.parent.parent.parent)
    load_env_file()
    check_required_env_vars()