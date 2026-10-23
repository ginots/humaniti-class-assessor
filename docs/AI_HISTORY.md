# Authentic AI interaction history

The original session history is preserved outside Git. The submission copy is
extracted from actual local Codex user/assistant message events, not reconstructed.
It preserves message order, marks redactions and omitted events, and excludes
internal reasoning, system/developer instructions, tool bodies and child sessions.

Run `scripts/export_history.py --session-id YOUR_LOCAL_SESSION_ID` locally using
the prepared Python environment. It writes private raw snapshots, hashes and a
separate redacted visible-message excerpt under `E:\HumanitiAI\private-history`.
Review that redacted file before attaching it to the submission. Raw logs and
credentials must never be committed or uploaded. A snapshot taken during work
is explicitly incomplete and cannot contain subsequent messages.
