# The /grade → /hint handle lives in Postgres, not a new Redis blob

The planned `/grade` + `/hint` split needs a way for `/hint` to recover the
failed-test detail and raw error from a specific submission without
trusting anything the client resends (answer leakage, prompt injection via
a forged `error_message`, a spoofable `attempt_number`). We decided the
handle is a `hint_token` UUID column on `interaction_history` — the row
`/grade` already writes — rather than a second copy of the grading result
in a new Redis `SETEX` blob.

Rejected alternative (a Redis blob keyed by UUID, TTL 900s): it stores data
Postgres already holds a second time, `/hint` still has to write the final
hint back to `interaction_history` regardless, and a Redis restart mid-lab
would 404 every pending hint. One store, not two. Redis keeps its existing
job — best-effort session state (`attempts`, `last_hint_level`) — but
`student_progress.attempts` in Postgres is authoritative for hint-level
escalation, so a Redis loss can't reset a student back to a level-1 hint.
