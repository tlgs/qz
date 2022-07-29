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

Running `qz log` will produce a readable summary of the most recently
recorded activities:

```
1927-10-31                                                                       3:25:00
├ discussion with Horton and Marrison [qz]                      │ 14:15-17:03 │ e8aad82a
└ Murray Hill tour [{}]                                         │ 08:59-09:36 │ 1e9b3f27

1880-07-13                                                                       3:46:00
├ read through piezoelectric theory notes [qz]                  │ 15:51-18:41 │ ae85f955
└ sit-down with the french brothers [qz]                        │ 10:13-11:09 │ af2551cc
```

When it comes to importing, only [toggl](https://track.toggl.com) is supported
at this time.

By design, there is no support for: activities in the future,
overlapping activities, or timezones (everything is `localtime`).

### Usage messages

These should give you a pretty good idea about the CLI feature set:

```
usage: qz [-h] [-v] <command> ...
usage: qz start [-h] [-m <msg>] [-p <proj>] [--at <datetime>]
usage: qz stop [-h] [-m <msg>] [-p <proj>] [--at <datetime>] [--discard]
usage: qz add [-h] [-m <msg>] [-p <proj>] <start> <stop>
usage: qz log [-h] [--since <datetime>] [--until <datetime>]
usage: qz delete [-h] <activity_uuid>
usage: qz import [-h] -t <tool> <file>
```

### What about X?

Unlike most other tools in the space, the storage layer is not hidden from the user;
it's a very simple SQLite database in a sane location (whatever `QZ_DB` is set to or
your platform's defaults).

If you need to do something that's not exposed by the CLI API, **you should** go ahead
and use it like a normal database.
Complex queries or batch activity insertions? `SELECT` and `INSERT`.

## Development

- install and setup project with `pip install -e .[dev]` and `pre-commit install`
