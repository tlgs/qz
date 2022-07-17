import argparse
import importlib.metadata
import itertools
import os
import re
import sqlite3
import sys
import textwrap
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import NoReturn

__version__ = importlib.metadata.version("qz")


def fatal(err: str | Exception) -> NoReturn:
    print(f"qz: {err}", file=sys.stderr)
    sys.exit(1)


def _db_path() -> Path:
    env_path = os.getenv("QZ_DB", "")

    if env_path.strip():
        return Path(env_path)

    # user data path
    if sys.platform != "linux":
        fatal("unsupported platform `{sys.platform}`")

    xdg_path = os.getenv("XDG_DATA_HOME", "")
    if xdg_path.strip():
        base_path = Path(xdg_path)
    else:
        base_path = Path("~/.local/share").expanduser()

    return base_path / "qz" / "store.db"


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
          NEW.start_dt <> OLD.start_dt
          OR NEW.stop_dt <> OLD.stop_dt
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

        CREATE TRIGGER IF NOT EXISTS no_empty_strings_after_insert
        AFTER INSERT on activities
        BEGIN
          UPDATE
            activities
          SET
            message = iif(NEW.message == '', NULL, NEW.message),
            project = iif(NEW.project == '', NULL, NEW.project)
          WHERE
            uuid = NEW.uuid;
        END;

        CREATE TRIGGER IF NOT EXISTS no_empty_strings_after_update
        AFTER UPDATE on activities
        BEGIN
          UPDATE
            activities
          SET
            message = iif(NEW.message == '', NULL, NEW.message),
            project = iif(NEW.project == '', NULL, NEW.project)
          WHERE
            uuid = NEW.uuid;
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


@contextmanager
def sqlite_db() -> Iterator[sqlite3.Connection]:
    """Create and close an SQLite database connection.

    Using a hand-rolled context manager to handle database connections as
    the builtin sqlite3 module does not close a connection when it goes out of scope;
    this is specially important as we want to quickly ditch the application when
    encountering an exception and a connection is open. See:
    - <https://softwareengineering.stackexchange.com/q/200522>
    - <https://eli.thegreenplace.net/2009/06/12/safely-using-destructors-in-python>
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

    try:
        yield conn
    finally:
        conn.commit()
        conn.close()


def parse_user_datetime(s: str) -> datetime:
    def just_time(s: str) -> datetime:
        return datetime.combine(date.today(), time.fromisoformat(s))

    for parsing_func in [datetime.fromisoformat, just_time]:
        try:
            return parsing_func(s)
        except ValueError:
            continue

    raise ValueError(f"could not parse `{s}` as a datetime")


def root_cmd(args: argparse.Namespace) -> None:
    with sqlite_db() as db_conn:
        row = db_conn.execute("SELECT * FROM running_activity").fetchone()

    if row:
        _, message, project, start, _ = row

        dt = datetime.fromisoformat(start)
        elapsed = datetime.now() - dt
        elapsed = elapsed - timedelta(microseconds=elapsed.microseconds)

        print(f"tracking {message or '{}'} ({project or '{}'}) for {elapsed}")

    else:
        print("no tracking ongoing")


def start_cmd(args: argparse.Namespace) -> None:
    if args.at is not None:
        try:
            at_dt = parse_user_datetime(args.at)
        except ValueError as e:
            fatal(e)
    else:
        at_dt = datetime.now()

    id_ = str(uuid.uuid4())
    with sqlite_db() as db_conn:
        try:
            db_conn.execute(
                "INSERT INTO activities VALUES (?, ?, ?, ?, ?)",
                (id_, args.message, args.project, at_dt, None),
            )
        except sqlite3.IntegrityError as e:
            if str(e) == "UNIQUE constraint failed: index 'stop_dt_single_null'":
                fatal("an activity is already running")

            fatal(e)

    print(id_)


def stop_cmd(args: argparse.Namespace) -> None:
    with sqlite_db() as db_conn:
        row = db_conn.execute("SELECT * FROM running_activity").fetchone()
        if not row:
            fatal("no running activity")

        id_, message, project, start, _ = row

        if args.discard:
            db_conn.execute("DELETE FROM activities WHERE uuid = ?", (id_,))
            return

        if args.message is not None:
            message = args.message
        if args.project is not None:
            project = args.project

        db_conn.execute(
            textwrap.dedent(
                """\
                UPDATE activities SET message = ?, project = ?, stop_dt = ?
                WHERE uuid = ?"""
            ),
            (message, project, datetime.now(), id_),
        )

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
    tmp = []
    if args.project is not None:
        tmp.append((args.project, "project == ?"))

    for arg, s in [(args.since, "start_dt >= ?"), (args.until, "stop_dt <= ?")]:
        if arg is not None:
            try:
                dt = parse_user_datetime(arg)
            except ValueError as e:
                fatal(e)

            tmp.append((dt, s))

    with sqlite_db() as db_conn:
        if tmp:
            params, predicates = zip(*tmp)
            rows = db_conn.execute(
                "SELECT * FROM activities WHERE stop_dt IS NOT NULL AND "
                + " AND ".join(predicates)
                + " ORDER BY start_dt DESC",
                params,
            ).fetchall()
        else:
            rows = db_conn.execute(
                textwrap.dedent(
                    """\
                    SELECT *
                    FROM activities
                    WHERE stop_dt IS NOT NULL
                    ORDER BY start_dt DESC"""
                )
            ).fetchall()

    if not rows:
        print("no recorded activities")
        return

    for i, (k, g) in enumerate(
        itertools.groupby(rows, key=lambda t: datetime.fromisoformat(t[3]).date())
    ):
        print(f"\n{k}" if i else k)
        for row in g:
            activity_uuid, message, project, start_dt, stop_dt = row

            id_ = activity_uuid[:8]
            message = message or "{}"
            project = project or "{}"
            start_time = datetime.fromisoformat(start_dt).time().isoformat("minutes")
            stop_time = datetime.fromisoformat(stop_dt).time().isoformat("minutes")

            activity_desc = f"{message} ⦻ {project}"
            print(f"  {activity_desc:51.51} | {start_time} - {stop_time} | {id_}")


def delete_cmd(args: argparse.Namespace) -> None:
    if args.activity_uuid is not None and len(args.activity_uuid) < 4:
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


def main() -> int:
    parser = ArgumentParser(
        description=textwrap.dedent(
            """\
            Minimal time tracking CLI app.

            Run with no arguments to get current tracking status."""
        ),
        formatter_class=SubcommandHelpFormatter,
        exit_on_error=True,
    )
    parser.add_argument(
        "-v", "--version", action="version", version=f"qz version {__version__}"
    )
    parser.set_defaults(func=root_cmd)

    subparsers = parser.add_subparsers(title="subcommands", metavar="<command>")

    parser_start = subparsers.add_parser("start", help="start tracking an activity")
    parser_start.add_argument("-m", "--message", help="set message", metavar="<msg>")
    parser_start.add_argument("-p", "--project", help="set project", metavar="<proj>")
    parser_start.add_argument(
        "--at", help="set alternative start datetime", metavar="<datetime>"
    )
    parser_start.set_defaults(func=start_cmd)

    parser_stop = subparsers.add_parser("stop", help="stop tracking an activity")
    parser_stop.add_argument(
        "-m", "--message", help="set/update message", metavar="<msg>"
    )
    parser_stop.add_argument(
        "-p", "--project", help="set/update project", metavar="<proj>"
    )
    parser_stop.add_argument("--discard", help="discard activity", action="store_true")
    parser_stop.set_defaults(func=stop_cmd)

    parser_add = subparsers.add_parser("add", help="add a parametrized activity")
    parser_add.add_argument("start", help="start datetime")
    parser_add.add_argument("stop", help="stop datetime")
    parser_add.add_argument("-m", "--message", help="set messsage", metavar="<msg>")
    parser_add.add_argument("-p", "--project", help="set project", metavar="<proj>")
    parser_add.set_defaults(func=add_cmd)

    parser_log = subparsers.add_parser("log", help="show activity logs")
    parser_log.add_argument(
        "-p", "--project", help="filter by project", metavar="<proj>"
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

    parser_delete = subparsers.add_parser("delete", help="delete an activity")
    parser_delete.add_argument("activity_uuid")
    parser_delete.set_defaults(func=delete_cmd)

    args = parser.parse_args()
    args.func(args)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
