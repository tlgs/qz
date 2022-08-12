# qz

qz is a barebones time-tracking CLI application:

  - single module in idiomatic Python (~500 SLOC); no third-party dependencies
  - simple SQLite database to manage state
  - minimal command interface to record and log activities

## Installation

On Arch Linux:

```
git clone --depth=1 https://github.com/tlgs/qz.git
cd qz/build
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

Any datetime supplied should be in a format that is parseable by
[`datetime.datetime.fromisoformat`](https://docs.python.org/3/library/datetime.html#datetime.datetime.fromisoformat)
or [`datetime.time.fromisoformat`](https://docs.python.org/3/library/datetime.html#datetime.time.fromisoformat).
The current date will be used when only the time is provided.

When it comes to importing, only [toggl](https://track.toggl.com) is supported
at this time.

By design, there is no support for: activities in the future,
overlapping activities, or timezones.

The database location can be configured using the `QZ_DB` environment variable.
You can run `qz --locate` to track down the database in use.

### What about X?

Unlike most other similar tools, the storage layer is not hidden away
as an implementation detail: it's a very simple SQLite database in a sane location.

If you need to do something that's not exposed by the command interface,
**you should** go ahead and take advantage of SQLite's ease of use.
Complex queries or dynamic batch insertions? `SELECT` and `INSERT`.

## Development

- install and setup project with `pip install -e .[dev]` and `pre-commit install`
- run tests with `coverage run` and inspect results with `coverage report`
