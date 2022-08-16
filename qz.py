import argparse
import csv
import datetime
import itertools
import os
import re
import sqlite3
import sys
import textwrap
import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any, NoReturn, Optional, Union

__version__ = "0.1.0-alpha"


def fatal(err: str | Exception) -> NoReturn:
    print(f"qz: {err}", file=sys.stderr)
    sys.exit(1)


def get_db_path() -> Path:
    """Get path to data store: `QZ_DB` env var or platform user data dir.

    See <https://github.com/platformdirs/platformdirs>.
    Consciously ignoring Android as a platform.
    """
    env_path = os.getenv("QZ_DB", "")

    if env_path.strip():
        return Path(env_path).resolve()

    # user data dir
    match sys.platform:
        case "darwin":
            base_path = Path("~/Library/Application Support")

        case "win32":
            base_path = Path("~/AppData/Local")

        case _:
            xdg_path = os.getenv("XDG_DATA_HOME", "")
            if xdg_path.strip():
                base_path = Path(xdg_path)
            else:
                base_path = Path("~/.local/share")

    return base_path.expanduser() / "qz" / "store.db"


def _init_db(f: Path) -> sqlite3.Connection:
    """Create database and return a connection.

    Partial expression index trick to constrain a single NULL:
    <https://momjian.us/main/blogs/pgblog/2017.html#April_3_2017>
    """
    f.parent.mkdir(parents=True, exist_ok=True)

    raw_script = textwrap.dedent(
        """\
        CREATE TABLE IF NOT EXISTS activities (
          uuid     TEXT PRIMARY KEY,
          message  TEXT,
          project  TEXT,
          start_dt TEXT NOT NULL,
          stop_dt  TEXT,

          CHECK (message IS NULL OR message != '')
          CHECK (project IS NULL OR project != '')
          CHECK (datetime(start_dt) IS NOT NULL)
          CHECK (datetime(stop_dt) IS NOT NULL OR stop_dt IS NULL)
          CHECK (datetime(stop_dt) > datetime(start_dt))
        ) WITHOUT ROWID, STRICT;

        CREATE UNIQUE INDEX IF NOT EXISTS stop_dt_single_null
        ON activities(stop_dt IS NULL)
        WHERE stop_dt IS NULL;

        CREATE TRIGGER IF NOT EXISTS validate_dates_before_insert
        BEFORE INSERT ON activities
        BEGIN
          WITH overlapping_dates AS (
            SELECT
              *
            FROM
              activities
            WHERE
              start_dt BETWEEN NEW.start_dt AND NEW.stop_dt
              OR stop_dt BETWEEN NEW.start_dt AND NEW.stop_dt
              OR NEW.start_dt BETWEEN start_dt AND stop_dt
          )
          SELECT
            CASE
              WHEN datetime(NEW.start_dt) > datetime('now', 'localtime')
                THEN RAISE(ABORT, 'start_dt is in the future')
              WHEN datetime(NEW.stop_dt) > datetime('now', 'localtime')
                THEN RAISE(ABORT, 'stop_dt is in the future')
              WHEN EXISTS(SELECT * FROM overlapping_dates)
                THEN RAISE(ABORT, 'overlapping activities')
            END;
        END;

        CREATE TRIGGER IF NOT EXISTS validate_dates_before_update
        BEFORE UPDATE ON activities
        WHEN
          NEW.start_dt IS NOT OLD.start_dt
          OR NEW.stop_dt IS NOT OLD.stop_dt
        BEGIN
          WITH overlapping_dates AS (
            SELECT
              *
            FROM
              activities
            WHERE
              NEW.uuid != OLD.uuid
              AND (
                start_dt BETWEEN NEW.start_dt AND NEW.stop_dt
                OR stop_dt BETWEEN NEW.start_dt AND NEW.stop_dt
                OR NEW.start_dt BETWEEN start_dt AND stop_dt
              )
          )
          SELECT
            CASE
              WHEN datetime(NEW.start_dt) > datetime('now', 'localtime')
                THEN RAISE(ABORT, 'start_dt is in the future')
              WHEN datetime(NEW.stop_dt) > datetime('now', 'localtime')
                THEN RAISE(ABORT, 'stop_dt is in the future')
              WHEN EXISTS(SELECT * FROM overlapping_dates)
                THEN RAISE(ABORT, 'overlapping activities')
            END;
        END;

        CREATE VIEW IF NOT EXISTS running_activity AS
        SELECT *
        FROM activities
        WHERE stop_dt IS NULL;
        """
    )

    conn = sqlite3.connect(f)
    with conn:
        conn.executescript(raw_script)

    return conn


@contextmanager
def sqlite_db() -> Iterator[sqlite3.Connection]:
    """Create and close an SQLite database connection.

    Using a hand-rolled context manager to handle database connections as
    the builtin sqlite3 module does not close a connection when it goes out of scope;
    this is specially important as we want to quickly ditch the application when
    encountering an exception and a connection is open. See:
    - <https://softwareengineering.stackexchange.com/q/200522>
    - <https://eli.thegreenplace.net/2009/06/12/safely-using-destructors-in-python>

    Can use something like `conn.set_trace_callback(print)`
    to facilitate statement debugging during development.
    """
    f = get_db_path()
    if not f.exists():
        conn = _init_db(f)
    else:
        conn = sqlite3.connect(f)

    try:
        # <https://www.sqlite.org/pragma.html#pragma_integrity_check>
        result, *_ = conn.execute("PRAGMA integrity_check").fetchone()
        assert result == "ok", "database did not pass integrity check"

        yield conn

        # let's make sure we only commit if no exception was raised:
        conn.commit()
    finally:
        conn.close()


def parse_user_datetime(s: str) -> datetime.datetime:
    def just_time(s: str) -> datetime.datetime:
        return datetime.datetime.combine(
            datetime.date.today(), datetime.time.fromisoformat(s)
        )

    for parsing_func in [datetime.datetime.fromisoformat, just_time]:
        try:
            return parsing_func(s)
        except ValueError:
            continue

    raise ValueError(f"could not parse `{s}` as a datetime")


def root_cmd(args: argparse.Namespace) -> None:
    with sqlite_db() as db_conn:
        row = db_conn.execute("SELECT * FROM running_activity").fetchone()

    if not row:
        print("no tracking ongoing")
        return

    _, message, project, start_dt, _ = row
    message = message or "∅"
    project = project or "∅"
    dt = datetime.datetime.fromisoformat(start_dt)

    elapsed = datetime.datetime.now() - dt
    elapsed -= datetime.timedelta(microseconds=elapsed.microseconds)

    print(f"tracking {message} [{project}] for {elapsed}")


def start_cmd(args: argparse.Namespace) -> None:
    if args.at is not None:
        try:
            dt = parse_user_datetime(args.at)
        except ValueError as e:
            fatal(e)
    else:
        dt = datetime.datetime.now()

    id_ = str(uuid.uuid4())
    with sqlite_db() as db_conn:
        try:
            db_conn.execute(
                "INSERT INTO activities VALUES (?, ?, ?, ?, ?)",
                (id_, args.message, args.project, dt, None),
            )
        except sqlite3.IntegrityError as e:
            match str(e):
                case "UNIQUE constraint failed: index 'stop_dt_single_null'":
                    fatal("an activity is already running")
                case _:
                    fatal(e)

    print(id_)


def stop_cmd(args: argparse.Namespace) -> None:
    if args.discard and (args.message or args.project or args.at):
        fatal("incompatible options: modifiers should not be used with discard")

    with sqlite_db() as db_conn:
        row = db_conn.execute("SELECT * FROM running_activity").fetchone()
        if not row:
            fatal("no running activity")

        id_, message, project, _, _ = row

        if args.discard:
            db_conn.execute("DELETE FROM activities WHERE uuid = ?", (id_,))
            print(id_)
            return

        if args.message is not None:
            message = args.message
        if args.project is not None:
            project = args.project

        if args.at is not None:
            try:
                dt = parse_user_datetime(args.at)
            except ValueError as e:
                fatal(e)
        else:
            dt = datetime.datetime.now()

        stmt = textwrap.dedent(
            """\
            UPDATE
              activities
            SET
              message = ?,
              project = ?,
              stop_dt = ?
            WHERE
              uuid = ?"""
        )

        try:
            db_conn.execute(stmt, (message, project, dt, id_))
        except sqlite3.IntegrityError as e:
            fatal(e)

    print(id_)


def add_cmd(args: argparse.Namespace) -> None:
    try:
        start_dt, stop_dt = [parse_user_datetime(s) for s in (args.start, args.stop)]
    except ValueError as e:
        fatal(e)

    id_ = str(uuid.uuid4())
    with sqlite_db() as db_conn:
        try:
            db_conn.execute(
                "INSERT INTO activities VALUES (?, ?, ?, ?, ?)",
                (id_, args.message, args.project, start_dt, stop_dt),
            )
        except sqlite3.IntegrityError as e:
            fatal(e)

    print(id_)


def log_cmd(args: argparse.Namespace) -> None:
    if args.today and (args.since or args.until):
        fatal("incompatible options: range modifiers should not be used with today")

    if args.since:
        try:
            since_dt = parse_user_datetime(args.since)
        except ValueError as e:
            fatal(e)
    elif args.today:
        since_dt = datetime.datetime.now().replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    else:
        since_dt = datetime.datetime.combine(
            datetime.date.today() - datetime.timedelta(days=7),
            datetime.time.min,
        )

    if args.until:
        try:
            until_dt = parse_user_datetime(args.until)
        except ValueError as e:
            fatal(e)
    else:
        until_dt = datetime.datetime.now()

    with sqlite_db() as db_conn:
        stmt = textwrap.dedent(
            """\
            SELECT
              *
            FROM
              activities
            WHERE
              start_dt >= ?
              AND stop_dt <= ?
            ORDER BY
              start_dt DESC"""
        )
        if not (args.today or args.since or args.until):
            stmt += "\nLIMIT 20"

        rows = db_conn.execute(stmt, (since_dt, until_dt)).fetchall()

    if not rows:
        print("no recorded activities")
        return

    def group_by_day(row: tuple[str, str, str, str, str]) -> datetime.date:
        _, _, _, start_dt, _ = row
        return datetime.datetime.fromisoformat(start_dt).date()

    def day_duration(group: list[tuple[str, str, str, str, str]]) -> datetime.timedelta:
        total = datetime.timedelta()
        for row in group:
            _, _, _, raw_start, raw_stop = row
            start_dt = datetime.datetime.fromisoformat(raw_start)
            stop_dt = datetime.datetime.fromisoformat(raw_stop)

            total += stop_dt - start_dt

        total -= datetime.timedelta(microseconds=total.microseconds)
        return total

    project_length = max(len(p) if p else 1 for _, _, p, _, _ in rows)
    message_length = 58 - project_length

    grouped_days = [(k, list(g)) for k, g in itertools.groupby(rows, group_by_day)]
    for i, (k, g) in enumerate(grouped_days):
        if i:
            print()
        print("\x1b[1m" + str(k) + str(day_duration(g)).rjust(78) + "\x1b[0m")

        for j, row in enumerate(g, start=1):
            activity_uuid, message, project, start_dt, stop_dt = row

            id_ = activity_uuid[:8]
            message = f"{message or '∅':{message_length}.{message_length}}"
            project = f"{project or '∅':{project_length}}"
            start_time = datetime.datetime.fromisoformat(start_dt).strftime("%H:%M")
            stop_time = datetime.datetime.fromisoformat(stop_dt).strftime("%H:%M")

            ladder = "├" if j < len(g) else "└"
            print(f"{ladder} {message} │ {project} │ {start_time}-{stop_time} │ {id_}")


def delete_cmd(args: argparse.Namespace) -> None:
    if len(args.activity_uuid) < 4:
        fatal(f"ambiguous uuid '{args.activity_uuid}'")

    with sqlite_db() as db_conn:
        expr = args.activity_uuid + "%"
        rows = db_conn.execute(
            "SELECT uuid FROM activities WHERE uuid LIKE ?", (expr,)
        ).fetchall()

        match len(rows):
            case 0:
                fatal(f"could not find matching uuid '{args.activity_uuid}'")
            case 1:
                ...
            case _:
                fatal(f"ambiguous uuid '{args.activity_uuid}': use the full identifier")

        id_, *_ = rows[0]
        db_conn.execute("DELETE FROM activities WHERE uuid = ?", (id_,))

    print(id_)


def import_cmd(args: argparse.Namespace) -> None:
    to_insert = []

    # no need to parse args.tool as we're only supporting 'toggl'
    try:
        with open(args.file, newline="") as csv_file:
            for row in csv.DictReader(csv_file):
                message = row["Description"]
                project = row["Project"]
                start_dt = datetime.datetime.combine(
                    datetime.date.fromisoformat(row["Start date"]),
                    datetime.time.fromisoformat(row["Start time"]),
                )
                stop_dt = datetime.datetime.combine(
                    datetime.date.fromisoformat(row["End date"]),
                    datetime.time.fromisoformat(row["End time"]),
                )

                id_ = str(uuid.uuid4())
                to_insert.append((id_, message, project, start_dt, stop_dt))

    except FileNotFoundError:
        fatal(f"no such file `{args.file}`")

    with sqlite_db() as db_conn:
        try:
            db_conn.executemany(
                "INSERT INTO activities VALUES (?, ?, ?, ?, ?)",
                to_insert,
            )
        except sqlite3.IntegrityError as e:
            fatal(e)

    for id_, *_ in to_insert:
        print(id_)


def status_cmd(args: argparse.Namespace) -> None:
    root_cmd(argparse.Namespace())


class ArgumentParser(argparse.ArgumentParser):
    """Patched argparse.ArgumentParser to customize error handling.

    <https://stackoverflow.com/q/5943249/5818220>
    <https://peps.python.org/pep-0389/#discussion-sys-stderr-and-sys-exit>
    """

    def error(self, message: str) -> NoReturn:
        pat = re.compile(r"argument <command>: invalid choice: '(.+?)'")
        if m := pat.match(message):
            message = f"'{m.group(1)}' is not a qz command"

        fatal(message)


class SubcommandHelpFormatter(argparse.RawDescriptionHelpFormatter):
    """Patched argparse.RawDescriptionHelpFormatter to remove subcommand metavar.

    <https://stackoverflow.com/q/13423540/5818220>
    """

    def _format_action(self, action: argparse.Action) -> str:
        parts = super()._format_action(action)
        if action.nargs == argparse.PARSER:
            _, *skipped_first = parts.split("\n")
            parts = "\n".join(skipped_first)
        return parts


class LocateAction(argparse.Action):
    """Custom action that mimics --help/--version behaviour for --locate.

    See source for argparse._VersionAction:
    <https://github.com/python/cpython/blob/3.10/Lib/argparse.py>
    """

    def __init__(self, option_strings: Sequence[str], dest: str):
        super().__init__(option_strings, dest, nargs=0, help=argparse.SUPPRESS)

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: Union[str, Sequence[Any], None],
        option_string: Optional[str] = None,
    ) -> NoReturn:
        print(get_db_path())
        sys.exit(0)


def main(args: Sequence[str] | None = None) -> int:
    parser = ArgumentParser(
        description=(
            "Barebones time tracking CLI app.\n"
            "\n"
            "Run with no arguments to get current tracking status."
        ),
        formatter_class=SubcommandHelpFormatter,
    )
    parser.add_argument(
        "-v", "--version", action="version", version=f"qz version {__version__}"
    )
    parser.add_argument("--locate", action=LocateAction)
    parser.set_defaults(func=root_cmd)

    subparsers = parser.add_subparsers(title="subcommands", metavar="<command>")

    parser_start = subparsers.add_parser(
        "start",
        help="start tracking an activity",
        description="Start tracking an activity.",
    )
    parser_start.add_argument("-m", "--message", help="set message", metavar="<msg>")
    parser_start.add_argument("-p", "--project", help="set project", metavar="<proj>")
    parser_start.add_argument(
        "--at", help="set alternative start datetime", metavar="<datetime>"
    )
    parser_start.set_defaults(func=start_cmd)

    parser_stop = subparsers.add_parser(
        "stop",
        usage=(
            "%(prog)s [-h] [-m <msg>] [-p <proj>] [--at <datetime>]\n"
            "       %(prog)s [-h] [--discard]"
        ),
        help="stop tracking an activity",
        description="Stop tracking an activity.",
    )
    parser_stop.add_argument(
        "-m", "--message", help="set/update message", metavar="<msg>"
    )
    parser_stop.add_argument(
        "-p", "--project", help="set/update project", metavar="<proj>"
    )
    parser_stop.add_argument(
        "--at", help="set alternative stop datetime", metavar="<datetime>"
    )
    parser_stop.add_argument("--discard", action="store_true", help="discard activity")
    parser_stop.set_defaults(func=stop_cmd)

    parser_add = subparsers.add_parser(
        "add",
        help="add a parametrized activity",
        description="Add a parametrized activity.",
    )
    parser_add.add_argument("start", help="start datetime", metavar="<start>")
    parser_add.add_argument("stop", help="stop datetime", metavar="<stop>")
    parser_add.add_argument("-m", "--message", help="set message", metavar="<msg>")
    parser_add.add_argument("-p", "--project", help="set project", metavar="<proj>")
    parser_add.set_defaults(func=add_cmd)

    parser_log = subparsers.add_parser(
        "log",
        help="show activity logs",
        usage=(
            "%(prog)s [-h] [--since <datetime>] [--until <datetime>]\n"
            "       %(prog)s [-h] [--today]"
        ),
        description=textwrap.dedent(
            """\
            Show activity logs.

            By default only shows the last 20 activities of the past 7 days.
            """
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser_log.add_argument(
        "--since",
        help="show activities more recent than a specific date",
        metavar="<datetime>",
    )
    parser_log.add_argument(
        "--until",
        help="show activities older than a specific date",
        metavar="<datetime>",
    )
    parser_log.add_argument(
        "--today", action="store_true", help="show activities recorded today"
    )
    parser_log.set_defaults(func=log_cmd)

    parser_delete = subparsers.add_parser(
        "delete", help="delete an activity", description="Delete an activity."
    )
    parser_delete.add_argument("activity_uuid", metavar="<activity_uuid>")
    parser_delete.set_defaults(func=delete_cmd)

    parser_import = subparsers.add_parser(
        "import",
        help="import activities from other tools",
        description="Import activities from other tools.",
    )
    parser_import.add_argument(
        "-t",
        "--tool",
        choices=["toggl"],
        required=True,
        help="specify tool (one of: toggl)",
        metavar="<tool>",
    )
    parser_import.add_argument("file", help="tool-specific data file", metavar="<file>")
    parser_import.set_defaults(func=import_cmd)

    parser_status = subparsers.add_parser(
        "status", description="Alias to root command without extra options."
    )
    parser_status.set_defaults(func=status_cmd)

    parsed_args = parser.parse_args(args)
    parsed_args.func(parsed_args)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
