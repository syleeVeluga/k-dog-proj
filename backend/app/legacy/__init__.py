"""55-item (2026-09-04) contracts, validation, arithmetic and intake shape, kept read-only.

The 55-item analysis/report/export API routes and screens were removed in PR-10; the pipeline modules
(`analysis`, `worker` steps, `evaluation`, `reporting`, `exports`) stay only because `worker.py` still imports them.

Stored runs of the superseded specification are read through these modules until each
infrastructure module is rebuilt for the 42-item specification. Nothing new is added here;
each remaining import is deleted in the PR that replaces its caller.
"""
