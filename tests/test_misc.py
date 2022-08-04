from pathlib import Path
from unittest.mock import patch

import pytest

from qz import get_db_path, main


@pytest.mark.parametrize(
    ("platform", "expected"),
    [
        pytest.param("linux", "~/.local/share/qz/store.db", id="linux"),
        pytest.param("win32", "~/AppData/Local/qz/store.db", id="win32"),
        pytest.param(
            "darwin", "~/Library/Application Support/qz/store.db", id="darwin"
        ),
    ],
)
def test_default_db_path(platform, expected):
    expected_path = Path(expected).expanduser()

    with patch.dict("os.environ") as patched_env, patch("sys.platform", platform):
        patched_env.pop("QZ_DB", None)

        assert get_db_path() == expected_path


@pytest.mark.parametrize("args", [["lolitos"], ["@rabanadas!"]])
def test_wrong_subcommand(capsys, args):
    with pytest.raises(SystemExit) as exc_info:
        main(args)

    assert exc_info.value.code == 1

    expected_stdout = ""
    expected_stderr = f"qz: '{args[0]}' is not a qz command\n"
    assert capsys.readouterr() == (expected_stdout, expected_stderr)
