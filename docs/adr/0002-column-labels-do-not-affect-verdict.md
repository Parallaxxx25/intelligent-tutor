# Column labels never affect the grading verdict

`test_runner.py` used to require exact, ordered column-name equality
between a submission and the Gold Query — a submission with correct values
but a missing or differently-named alias (e.g. Gold Query `AS full_name`,
submission with no alias) failed outright. We decided the verdict is
determined by **column count + row values only**; a name mismatch becomes a
`label_mismatch` flag fed to the Diagnostician instead of a failure.

The alternative — failing on label mismatch, or requiring per-problem
strict-label flags — was rejected because it fails semantically-correct SQL
on a naming technicality the problem text often doesn't even specify.
Accepted risk: a wrong column whose values coincide with the right one can
now pass; judged negligible for this catalog's data.
