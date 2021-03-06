import argparse
import collections.abc
import contextlib
import csv
import datetime
import importlib.metadata
import itertools
import os
import pathlib
import re
import sqlite3
import sys
import textwrap
import typing
import uuid

__version__ = importlib.metadata.version("qz")


def fatal(err: str | Exception) -> typing.NoReturn:
    print(f"qz: {err}", file=sys.stderr)
    sys.exit(1)


def _db_path() -> pathlib.Path:
    env_path = os.getenv("QZ_DB", "")

    if env_path.strip():
        return pathlib.Path(env_path)

    # user data path
    if sys.platform != "linux":
        fatal("unsupported platform `{sys.platform}`")

    xdg_path = os.getenv("XDG_DATA_HOME", "")
    if xdg_path.strip():
        base_path = pathlib.Path(xdg_path)
    else:
        base_path = pathlib.Path("~/.local/share").expanduser()

    return base_path / "qz" / "store.db"


def _init_db(f: pathlib.Path) -> sqlite3.Connection:
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

    print("init db at", f.resolve())
    return conn


@contextlib.contextmanager
def sqlite_db() -> collections.abc.Iterator[sqlite3.Connection]:
    """Create and close an SQLite database connection.

    Using a hand-rolled context manager to handle database connections as
    the builtin sqlite3 module does not close a connection when it goes out of scope;
    this is specially important as we want to quickly ditch the application when
    encountering an exception and a connection is open. See:
    - <https://softwareengineering.stackexchange.com/q/200522>
    - <https://eli.thegreenplace.net/2009/06/12/safely-using-destructors-in-python>

    Can use something like `conn.set_trace_callback(print)`
    to faciliate statement debugging during development.
    """
    f = _db_path()
    if not f.exists():
        conn = _init_db(f)
    else:
        conn = sqlite3.connect(f)

        # <https://www.sqlite.org/pragma.html#pragma_integrity_check>
        result, *_ = conn.execute("PRAGMA integrity_check").fetchone()
        if result != "ok":
            conn.close()
            fatal("database did not pass integrity check")

    conn.row_factory = sqlite3.Row
    try:
        yield conn

        # if an exception occurs (e.g. `fatal`) the transaction is not committed
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
    message = message or "{}"
    project = project or "{}"
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
    with sqlite_db() as db_conn:
        row = db_conn.execute("SELECT * FROM running_activity").fetchone()
        if not row:
            fatal("no running activity")

        id_, message, project, _, _ = row

        if args.discard:
            db_conn.execute("DELETE FROM activities WHERE uuid = ?", (id_,))
            return

        if args.message is not None:
            message = None if args.message == "" else args.message
        if args.project is not None:
            project = None if args.project == "" else args.project

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
    if args.since is not None:
        try:
            since_dt = parse_user_datetime(args.since)
        except ValueError as e:
            fatal(e)
    else:
        since_dt = datetime.datetime.combine(
            datetime.date.today() - datetime.timedelta(days=7),
            datetime.time.min,
        )

    if args.until is not None:
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
              start_dt DESC
            """
        )

        rows = db_conn.execute(stmt, (since_dt, until_dt)).fetchall()

    if not rows:
        print("no recorded activities")
        return

    grouped_days = [
        (k, list(g))
        for k, g in itertools.groupby(
            rows,
            key=lambda row: datetime.datetime.fromisoformat(row["start_dt"]).date(),
        )
    ]

    for i, (k, g) in enumerate(grouped_days):
        total_duration = sum(
            (
                datetime.datetime.fromisoformat(row["stop_dt"])
                - datetime.datetime.fromisoformat(row["start_dt"])
                for row in g
            ),
            start=datetime.timedelta(),
        )
        total_duration -= datetime.timedelta(microseconds=total_duration.microseconds)

        # print header
        print(
            ("\n" if i else "")
            + "\x1b[1m"
            + str(k)
            + str(total_duration).rjust(78)
            + "\x1b[0m"
        )

        for j, row in enumerate(g, start=1):
            activity_uuid, message, project, start_dt, stop_dt = row

            id_ = activity_uuid[:8]
            message = message or "{}"
            project = project or "{}"
            start_time = (
                datetime.datetime.fromisoformat(start_dt).time().isoformat("minutes")
            )
            stop_time = (
                datetime.datetime.fromisoformat(stop_dt).time().isoformat("minutes")
            )
            activity_desc = f"{message} [{project}]"

            ladder = "???" if j < len(g) else "???"
            print(f"{ladder} {activity_desc:61.61} ??? {start_time}-{stop_time} ??? {id_}")


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


class ArgumentParser(argparse.ArgumentParser):
    """Patched argparse.ArgumentParser to customize error handling.

    <https://stackoverflow.com/q/5943249/5818220>
    <https://peps.python.org/pep-0389/#discussion-sys-stderr-and-sys-exit>
    """

    def error(self, message: str) -> typing.NoReturn:
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


def main() -> int:
    parser = ArgumentParser(
        description=textwrap.dedent(
            """\
            Minimal time tracking CLI app.

            Run with no arguments to get current tracking status."""
        ),
        formatter_class=SubcommandHelpFormatter,
    )
    parser.add_argument(
        "-v", "--version", action="version", version=f"qz version {__version__}"
    )
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
    parser_add.add_argument("start", help="start datetime")
    parser_add.add_argument("stop", help="stop datetime")
    parser_add.add_argument("-m", "--message", help="set messsage", metavar="<msg>")
    parser_add.add_argument("-p", "--project", help="set project", metavar="<proj>")
    parser_add.set_defaults(func=add_cmd)

    parser_log = subparsers.add_parser(
        "log",
        help="show activity logs",
        description=textwrap.dedent(
            """\
            Show activity logs.

            By default only shows activities in the past 7 days.
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
    parser_log.set_defaults(func=log_cmd)

    parser_delete = subparsers.add_parser(
        "delete", help="delete an activity", description="Delete an activity."
    )
    parser_delete.add_argument("activity_uuid")
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
        help="specify tool",
        metavar="<tool>",
    )
    parser_import.add_argument("file", help="tool-specific data file")
    parser_import.set_defaults(func=import_cmd)

    args = parser.parse_args()
    args.func(args)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
