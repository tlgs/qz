"""qz testing module.

All of the "important" functionality is actually offloaded
to SQLite so these are mostly sloppy interface tests.

monkeypatch vs mock.patch:
    - <https://github.com/pytest-dev/pytest/issues/4576>

Mocking datetime.datetime.now:
  - <https://stackoverflow.com/q/4481954/5818220>
  - <https://stackoverflow.com/q/13073281/5818220>

Different scopes for same fixture:
  - <https://github.com/pytest-dev/pytest/issues/3425>
"""
