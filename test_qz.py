"""qz testing module.

All of the "important" functionality is actually offloaded
to SQLite so these are mostly sloppy interface tests.

monkeypatch vs mock.patch:
    - <https://github.com/pytest-dev/pytest/issues/4576>

Mocking datetime.datetime.now:
  - <https://stackoverflow.com/q/4481954/5818220>
  - <https://stackoverflow.com/q/13073281/5818220>

Different scopes for same fixture:
  - <https://github.com/pytest-dev/pytest/issues/3425>
"""
import datetime
import os
import pathlib
import sys
import uuid
from unittest.mock import patch

import pytest

import qz

MOCKED_NOW = datetime.datetime(2022, 7, 30, 8, 0, 0)


def idfn(v):
    return str(v)[1:-1]


@pytest.fixture
def mock_env_db(tmp_path):
    tmp_db = pathlib.Path(tmp_path) / "store.db"
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
    with qz.sqlite_db() as conn:
        conn.executemany("INSERT INTO activities VALUES (?, ?, ?, ?, ?)", data)

    # capture the 'init db at {}' message
    capsys.readouterr()


@pytest.fixture
def running_db(stopped_db):
    start_dt = MOCKED_NOW - datetime.timedelta(minutes=13, seconds=37)

    id_ = str(uuid.uuid4())
    with qz.sqlite_db() as conn:
        conn.execute(
            "INSERT INTO activities VALUES (?, ?, ?, ?, ?)",
            (id_, "orbital simulations", "artemis i", start_dt, None),
        )


@pytest.mark.parametrize(
    ("platform", "expected"),
    [
        pytest.param("linux", "~/.local/share/qz/store.db", id="linux"),
        pytest.param(
            "win32",
            "",
            marks=pytest.mark.skipif(
                sys.platform != "win32", reason="only runs on windows"
            ),
            id="win32",
        ),
        pytest.param(
            "darwin", "~/Library/Application Support/qz/store.db", id="darwin"
        ),
    ],
)
def test_default_db_path(platform, expected):
    # UNTESTED FOR WINDOWS
    expected_path = pathlib.Path(expected).expanduser()

    with patch.dict("os.environ") as patched_env, patch("sys.platform", platform):
        patched_env.pop("QZ_DB", None)

        assert qz.get_db_path() == expected_path


@pytest.mark.parametrize("args", [["lolitos"], ["@rabanadas!"]], ids=idfn)
def test_wrong_subcommand(capsys, args):
    with pytest.raises(SystemExit) as exc_info:
        qz.main(args)

    assert exc_info.value.code == 1

    expected_stdout = ""
    expected_stderr = f"qz: '{args[0]}' is not a qz command\n"
    assert capsys.readouterr() == (expected_stdout, expected_stderr)


class TestRoot:
    @pytest.mark.parametrize("args", [["-h"], ["--help"], ["--help", "add"]], ids=idfn)
    def test_help_message(self, capsys, args):
        # argparse.ArgumentParser uses sys.argv[0] to determine how to display
        # the name of the program in help messages.
        #
        # argparse will automatically sys.exit(0)
        with patch("sys.argv", ["qz"]), pytest.raises(SystemExit) as exc_info:
            qz.main(args)

        assert exc_info.value.code == 0

        captured_out, captured_err = capsys.readouterr()
        assert captured_out.startswith("usage: qz [-h] [-v] <command> ...")
        assert captured_err == ""

    @pytest.mark.parametrize("args", [["--version"], ["--version", "stop"]], ids=idfn)
    def test_version_message(self, capsys, args):
        # argparse will automatically sys.exit(0)
        with pytest.raises(SystemExit) as exc_info:
            qz.main(args)

        assert exc_info.value.code == 0

        expected_stdout = f"qz version {qz.__version__}\n"
        expected_stderr = ""
        assert capsys.readouterr() == (expected_stdout, expected_stderr)

    def test_first_run(self, capsys, mock_env_db):
        qz.main([])

        db_path = os.getenv("QZ_DB")

        expected_stdout = f"init db at {db_path}\nno tracking ongoing\n"
        expected_stderr = ""
        assert capsys.readouterr() == (expected_stdout, expected_stderr)

    def test_nothing_running(self, capsys, stopped_db):
        qz.main([])

        expected_stdout = "no tracking ongoing\n"
        expected_stderr = ""
        assert capsys.readouterr() == (expected_stdout, expected_stderr)

    def test_something_running(self, capsys, running_db):
        with patch(f"{qz.__name__}.datetime", wraps=datetime) as dt:
            dt.datetime.now.return_value = MOCKED_NOW
            qz.main([])

        expected_stdout = "tracking orbital simulations [artemis i] for 0:13:37\n"
        expected_stderr = ""
        assert capsys.readouterr() == (expected_stdout, expected_stderr)


class TestStart:
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
        ids=idfn,
    )
    def test_good(self, capsys, stopped_db, args):
        with qz.sqlite_db() as conn:
            n, *_ = conn.execute("SELECT COUNT(*) FROM activities").fetchone()

        with patch(f"{qz.__name__}.datetime", wraps=datetime) as dt:
            dt.date.today.return_value = MOCKED_NOW.date()
            qz.main(args)

        with qz.sqlite_db() as conn:
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
            ["start", "--at", "?!"],
            ["start", "--at", "30:05"],
            ["start", "--at", "-01:05"],
            ["start", "--at", "3022-07-30 08:00"],
        ],
        ids=idfn,
    )
    def test_bad(self, stopped_db, args):
        with pytest.raises(SystemExit) as exc_info:
            qz.main(args)

        assert exc_info.value.code == 1

    def test_already_running(self, capsys, running_db):
        with pytest.raises(SystemExit) as exc_info:
            qz.main(["start"])

        assert exc_info.value.code == 1

        expected_stdout = ""
        expected_stderr = "qz: an activity is already running\n"
        assert capsys.readouterr() == (expected_stdout, expected_stderr)


class TestStop:
    @pytest.mark.parametrize(
        "args",
        [
            ["stop"],
            ["stop", "-m", "not kerbal gaming"],
            ["stop", "--at", "2022-07-30 09:45"],
            ["stop", "--at", "13:37"],
        ],
        ids=idfn,
    )
    def test_good(self, capsys, running_db, args):
        with patch(f"{qz.__name__}.datetime", wraps=datetime) as dt:
            dt.date.today.return_value = MOCKED_NOW.date()
            qz.main(args)

        with qz.sqlite_db() as conn:
            n, *_ = conn.execute("SELECT COUNT(*) FROM running_activity").fetchone()
            rows = conn.execute("SELECT uuid FROM activities").fetchall()

        assert n == 0

        activity_uuids = [u for u, *_ in rows]
        captured_out, captured_err = capsys.readouterr()

        assert captured_out.strip() in activity_uuids
        assert captured_err == ""

    @pytest.mark.parametrize("args", [["stop"], ["stop", "--discard"]], ids=idfn)
    def test_not_running(self, capsys, stopped_db, args):
        with pytest.raises(SystemExit) as exc_info:
            qz.main(args)

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
        ids=idfn,
    )
    def test_bad(self, running_db, args):
        with pytest.raises(SystemExit) as exc_info:
            qz.main(args)

        assert exc_info.value.code == 1

    def test_discard(self, capsys, running_db):
        with qz.sqlite_db() as conn:
            id_, *_ = conn.execute("SELECT uuid FROM running_activity").fetchone()
            n, *_ = conn.execute("SELECT COUNT(*) FROM activities").fetchone()

        qz.main(["stop", "--discard"])

        with qz.sqlite_db() as conn:
            m, *_ = conn.execute("SELECT COUNT(*) FROM activities").fetchone()

        assert m == n - 1
        assert capsys.readouterr() == (id_ + "\n", "")
