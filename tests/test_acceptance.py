"""Pytest wrapper around the business-rule acceptance scenarios.

`app.acceptance` is the single source of truth: the Validation screen runs the
same scenarios through `app.acceptance.run_all`, so the screen and CI cannot
drift apart. Each scenario builds its own isolated in-memory database and drives
the real service layer.
"""

from __future__ import annotations

from app import acceptance


def test_all_scenarios_pass():
    results = acceptance.run_all()
    assert results, "no acceptance scenarios ran"
    failures = [
        f"{r.id}. {r.name}\n    expected: {r.expected}\n    actual:   {r.actual}"
        + (f"\n    detail:   {r.detail}" if r.detail else "")
        for r in results
        if not r.passed
    ]
    assert not failures, "failing acceptance scenarios:\n" + "\n".join(failures)


def test_summary_counts():
    results = acceptance.run_all()
    summary = acceptance.summarise(results)
    assert summary["total"] == len(acceptance.SCENARIOS)
    assert summary["passed"] + summary["failed"] == summary["total"]
