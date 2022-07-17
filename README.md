# qz

Minimal time tracking CLI application.

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
```

## Developing

- install and setup project with `pip install -e .[dev]` and `pre-commit install`
