import datetime
from unittest.mock import patch

import pytest

from qz import __name__ as qz_module
from qz import main, sqlite_db


@pytest.mark.parametrize(
    "args",
    [
        ["stop"],
        ["stop", "-m", "not kerbal gaming"],
        ["stop", "--at", "2022-07-30 09:45"],
        ["stop", "--at", "13:37"],
    ],
)
def test_good(capsys, running_db, frozen_now, args):
    with patch(f"{qz_module}.datetime", wraps=datetime) as dt:
        dt.date.today.return_value = frozen_now.date()
        main(args)

    with sqlite_db() as conn:
        n, *_ = conn.execute("SELECT COUNT(*) FROM running_activity").fetchone()
        rows = conn.execute("SELECT uuid FROM activities").fetchall()

    assert n == 0

    activity_uuids = [u for u, *_ in rows]
    captured_out, captured_err = capsys.readouterr()

    assert captured_out.strip() in activity_uuids
    assert captured_err == ""


@pytest.mark.parametrize("args", [["stop"], ["stop", "--discard"]])
def test_not_running(capsys, stopped_db, args):
    with pytest.raises(SystemExit) as exc_info:
        main(args)

    assert exc_info.value.code == 1

    expected_stdout = ""
    expected_stderr = "qz: no running activity\n"
    assert capsys.readouterr() == (expected_stdout, expected_stderr)


@pytest.mark.parametrize(
    "args",
    [
        ["stop", "--message"],
        ["stop", "-m", ""],
        ["stop", "--project", ""],
        ["stop", "--at", "##"],
        ["stop", "--at", "73:31"],
        ["stop", "--at", "+05:03"],
        ["stop", "--at", "3022-07-30 08:00"],
        ["stop", "--discard", "--at", "23:59"],
        ["stop", "-m", "kerbal gaming", "--discard"],
    ],
)
def test_bad(running_db, args):
    with pytest.raises(SystemExit) as exc_info:
        main(args)

    assert exc_info.value.code == 1


def test_discard(capsys, running_db):
    with sqlite_db() as conn:
        id_, *_ = conn.execute("SELECT uuid FROM running_activity").fetchone()
        n, *_ = conn.execute("SELECT COUNT(*) FROM activities").fetchone()

    main(["stop", "--discard"])

    with sqlite_db() as conn:
        m, *_ = conn.execute("SELECT COUNT(*) FROM activities").fetchone()

    assert m == n - 1
    assert capsys.readouterr() == (id_ + "\n", "")
