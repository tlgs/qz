# qz

qz is a _really_ minimal time tracking CLI application.

Here's a quick overview:

- uses a simple SQLite database to manage state
- exposes a simple and bare interface to record activities
- written in less than 500 SLOC of idiomatic Python; no third-party dependencies

## Installation

On Arch Linux:

```
git clone git@github.com:tlgs/qz.git
cd qz
makepkg -csri
```

Through pip (VCS support):

```
pip install git+https://github.com/tlgs/qz.git
```

## Usage

Running `qz -h` should give you all the information you need to get started:

```
usage: qz [-h] [-v] <command> ...

Minimal time tracking CLI app.

Run with no arguments to get current tracking status.

options:
  -h, --help     show this help message and exit
  -v, --version  show program's version number and exit

subcommands:
    start        start tracking an activity
    stop         stop tracking an activity
    add          add a parametrized activity
    log          show activity logs
    delete       delete an activity
    import       import activities from other tools
```

There is not much metadata that can be associated with an activity -
there's `message` (i.e. description) and `project`.
It should be pretty straightforward what these mean.

Any datetime supplied by the user should be in a format that is parseable by
[`datetime.datetime.fromisoformat`](https://docs.python.org/3/library/datetime.html#datetime.datetime.fromisoformat)
or [`datetime.time.fromisoformat`](https://docs.python.org/3/library/datetime.html#datetime.time.fromisoformat).
The current date will be used when only the time is provided.

When it comes to importing, only [toggl](https://track.toggl.com) is supported
at this time.

By design, there is no support for: activities in the future,
overlapping activities, or timezones (everything is `localtime`).

### What about X?

Unlike most other tools in the space, the storage layer is not hidden from the user;
it's a very simple SQLite database in a sane location (whatever `QZ_DB` is set to or
your platform's defaults).

If you need to do something that's not exposed by the CLI API, **you should** go ahead
take advantage of SQLite's ease of use.
Complex queries or dynamic batch insertions? `SELECT` and `INSERT`.

### Recipes

```sql
SELECT
  project,
  SUM(unixepoch(stop_dt) - unixepoch(start_dt)) / 3600 AS total_hours
FROM
  activities
GROUP BY
  project
ORDER BY
  total_hours DESC;
```

## Development

- install and setup project with `pip install -e .[dev]` and `pre-commit install`
- run tests with `coverage run` and inspect results with `coverage report`
