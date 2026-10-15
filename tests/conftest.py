"""On GitHub Actions, put a one-line error next to each failed test in the log."""
from __future__ import annotations

import os


def pytest_runtest_logreport(report):
    if report.failed and os.environ.get("GITHUB_ACTIONS"):
        crash = getattr(report.longrepr, "reprcrash", None)
        text = crash.message if crash else str(report.longrepr)
        reason = text.splitlines()[0][:300] if text else "failed"
        print("\n::error title=%s failed::%s" % (report.nodeid.split("::")[-1], reason), flush=True)
