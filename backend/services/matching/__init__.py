"""Track-identity matching for the Upscale section.

This package owns the math behind "is this DJCity result the same recording
as the local 128 kbps file?" — title/artist normalization, similarity
scoring, audio fingerprinting, and the confidence-band decision policy.

Modules land across PRs 2–8 of the AI slice (see
``posts/93e17e1d-ebbb-45b9-86c1-a25f0541ee7b/i-want-to-build-another-section-in-this-project-for-plan-ai.md``):

- ``normalize`` — title/artist cleaner; pure regex, no network.
- ``fingerprint`` — Chromaprint wrapper (``fpcalc``).
- ``score`` — composite similarity scorer.
- ``decide`` — band policy + ``evaluate_swap`` post-download gate.
- ``eval`` — golden set + harness + report.
"""
