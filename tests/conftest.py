import datetime
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

from qz import sqlite_db


def pytest_make_parametrize_id(config, val, argname):
    if argname == "args":
        cleaned_args = [f'"{v}"' if (" " in v or v == "") else v for v in val]
        return " ".join(cleaned_args)

    return None


def pytest_collection_modifyitems(session, config, items):
    order = ["misc", "root", "start", "stop", "add", "log", "delete", "import"]

    def sort_func(pytest_item):
        p, *_ = pytest_item.reportinfo()
        cmd = p.stem[5:]
        return order.index(cmd)

    items.sort(key=sort_func)


@pytest.fixture(scope="session")
def frozen_now():
    return datetime.datetime(2022, 7, 30, 9, 0, 0)


@pytest.fixture
def mock_env_db(tmp_path):
    tmp_db = Path(tmp_path) / "store.db"
    with patch.dict("os.environ", {"QZ_DB": str(tmp_db)}):
        yield


@pytest.fixture
def stopped_db(capsys, mock_env_db):
    id1, id2, id3 = [str(uuid.uuid4()) for _ in range(3)]
    data = [
        (id1, "call with leslie", "manhattan", "1942-12-15 12:34", "1942-12-15 14:13"),
        (id2, "talk with robert", "manhattan", "1943-01-01 08:00", "1943-01-01 09:00"),
        (id3, "trinity test", "manhattan", "1945-07-16 08:01", "1945-07-16 17:00"),
    ]
    with sqlite_db() as conn:
        conn.executemany("INSERT INTO activities VALUES (?, ?, ?, ?, ?)", data)


@pytest.fixture
def running_db(stopped_db, frozen_now):
    start_dt = frozen_now - datetime.timedelta(minutes=13, seconds=37)

    id_ = str(uuid.uuid4())
    with sqlite_db() as conn:
        conn.execute(
            "INSERT INTO activities VALUES (?, ?, ?, ?, ?)",
            (id_, "orbital simulations", "artemis i", start_dt, None),
        )
