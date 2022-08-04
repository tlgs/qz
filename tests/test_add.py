import datetime
from unittest.mock import patch

import pytest

from qz import __name__ as qz_module
from qz import main, sqlite_db


@pytest.mark.parametrize(
    "args",
    [
        ["add", "1969-07-16 13:32:00", "1969-07-24 16:50:35"],
        ["add", "08:00", "20:00", "-m", "orion stacking"],
    ],
)
def test_good(capsys, stopped_db, frozen_now, args):
    with sqlite_db() as conn:
        n, *_ = conn.execute("SELECT COUNT(*) FROM activities").fetchone()

    with patch(f"{qz_module}.datetime", wraps=datetime) as dt:
        dt.date.today.return_value = frozen_now.date()
        main(args)

    with sqlite_db() as conn:
        rows = conn.execute("SELECT uuid FROM activities").fetchall()

    assert len(rows) == n + 1

    activity_uuids = [u for u, *_ in rows]
    captured_out, captured_err = capsys.readouterr()

    assert captured_out.strip() in activity_uuids
    assert captured_err == ""


@pytest.mark.parametrize(
    "args",
    [
        ["add"],
        ["add", "10:00"],
        ["add", "10:00", "10:65"],
        ["add", "09:99", "10:55"],
        ["add", "10:00", "10:55", "-m"],
        ["add", "10:00", "10:55", "-m", ""],
        ["add", "10:00", "10:55", "-p", ""],
    ],
)
def test_bad(stopped_db, args):
    with pytest.raises(SystemExit) as exc_info:
        main(args)

    assert exc_info.value.code == 1
