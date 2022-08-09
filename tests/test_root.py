import datetime
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from qz import __name__ as qz_module
from qz import __version__ as qz_version
from qz import main


@pytest.mark.parametrize("args", [["-h"], ["--help"], ["--help", "add"]])
def test_help_message(capsys, args):
    with patch("sys.argv", ["qz"]), pytest.raises(SystemExit) as exc_info:
        main(args)

    assert exc_info.value.code == 0

    captured_out, captured_err = capsys.readouterr()
    assert captured_out.startswith("usage: qz [-h] [-v] <command> ...")
    assert captured_err == ""


@pytest.mark.parametrize("args", [["--version"], ["--version", "stop"]])
def test_version_message(capsys, args):
    with pytest.raises(SystemExit) as exc_info:
        main(args)

    assert exc_info.value.code == 0

    expected_stdout = f"qz version {qz_version}\n"
    expected_stderr = ""
    assert capsys.readouterr() == (expected_stdout, expected_stderr)


@pytest.mark.parametrize("args", [["--locate"], ["--locate", "import"]])
def test_locate_message(capsys, mock_env_db, args):
    with pytest.raises(SystemExit) as exc_info:
        main(args)

    assert exc_info.value.code == 0

    db_path = Path(os.getenv("QZ_DB")).resolve()

    expected_stdout = f"{db_path}\n"
    expected_stderr = ""
    assert capsys.readouterr() == (expected_stdout, expected_stderr)


def test_first_run(capsys, mock_env_db):
    main([])

    db_path = os.getenv("QZ_DB")

    expected_stdout = f"init db at {db_path}\nno tracking ongoing\n"
    expected_stderr = ""
    assert capsys.readouterr() == (expected_stdout, expected_stderr)


def test_nothing_running(capsys, stopped_db):
    main([])

    expected_stdout = "no tracking ongoing\n"
    expected_stderr = ""
    assert capsys.readouterr() == (expected_stdout, expected_stderr)


def test_something_running(capsys, running_db, frozen_now):
    with patch(f"{qz_module}.datetime", wraps=datetime) as dt:
        dt.datetime.now.return_value = frozen_now
        main([])

    expected_stdout = "tracking orbital simulations [artemis i] for 0:13:37\n"
    expected_stderr = ""
    assert capsys.readouterr() == (expected_stdout, expected_stderr)
