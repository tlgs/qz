import os
import tempfile
from pathlib import Path

import pytest

from qz import __version__, main, sqlite_db


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as dirname:
        yield dirname


@pytest.fixture
def mock_env_db(monkeypatch, tmp_dir):
    tmp_db_path = Path(tmp_dir) / "store.db"
    monkeypatch.setenv("QZ_DB", str(tmp_db_path))


@pytest.fixture
def db(capsys, mock_env_db):
    with sqlite_db():
        ...

    capsys.readouterr()


def idfn(v):
    return str(v)[1:-1]


def test_first_run(capsys, mock_env_db):
    main([])

    db_path = os.getenv("QZ_DB")
    assert capsys.readouterr() == (f"init db at {db_path}\nno tracking ongoing\n", "")


@pytest.mark.xfail
def test_help_message(capsys):
    raise NotImplementedError


@pytest.mark.parametrize("args", (["--version"], ["--version", "stop"]), ids=idfn)
def test_version_message(capsys, args):
    with pytest.raises(SystemExit):
        main(args)

    assert capsys.readouterr() == (f"qz version {__version__}\n", "")


def test_stop_when_not_running(capsys, db):
    with pytest.raises(SystemExit):
        main(["stop"])

    assert capsys.readouterr() == ("", "qz: no running activity\n")
