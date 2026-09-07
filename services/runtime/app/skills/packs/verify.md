# Coding verify

After a successful edit/write, run the same issue repro command and related tests. Case-insensitive table/QDP issues: replay the sample with `.lower()` / casefold even when the issue text is already lowercase. Hidden tests may use tokens like `NO` that the issue sample omitted.

Do not treat a green in-repo pytest as sufficient when issue_repro is armed.
