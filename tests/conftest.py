import os
from pathlib import Path

import pytest


@pytest.fixture(scope="session", autouse=True)
def isolated_db(tmp_path_factory):
    path = tmp_path_factory.mktemp("lifevault") / "test.db"
    os.environ["LIFE_DB"] = str(path)
    return Path(path)
