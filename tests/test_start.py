import datetime
from unittest.mock import patch

import pytest

from qz import __name__ as qz_module
from qz import main, sqlite_db


@pytest.mark.parametrize(
    "args",
    [
        ["start"],
        ["start", "--at", "2022-07-30 08:53"],
        ["start", "--at", "07:32"],
        ["start", "-m", "kerbal gaming"],
        ["start", "--project", "artemis i"],
        ["start", "--message", "kerbal gaming", "-p", "artemis i"],
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
        ["start", "-m"],
        ["start", "-m", ""],
        ["start", "--project", ""],
    ],
)
def test_bad_metadata(stopped_db, args):
    with pytest.raises(SystemExit) as exc_info:
        main(args)

    assert exc_info.value.code == 1


@pytest.mark.parametrize(
    "args",
    [
        ["start", "--at", "?!"],
        ["start", "--at", "30:05"],
        ["start", "--at", "-01:05"],
    ],
)
def test_bad_datetime(stopped_db, args):
    with pytest.raises(SystemExit) as exc_info:
        main(args)

    assert exc_info.value.code == 1


def test_future_datetime(stopped_db):
    with pytest.raises(SystemExit) as exc_info:
        main(["start", "--at", "3022-07-30 08:00"])

    assert exc_info.value.code == 1


def test_already_running(capsys, running_db):
    with pytest.raises(SystemExit) as exc_info:
        main(["start"])

    assert exc_info.value.code == 1

    expected_stdout = ""
    expected_stderr = "qz: an activity is already running\n"
    assert capsys.readouterr() == (expected_stdout, expected_stderr)
