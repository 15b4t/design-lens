# Worked example: Express middleware chain

A real run of the pipeline, kept so the output can be judged. Subject: Express 5.3.0 (commit `bcc0551`)
with its installed dependencies `router@2.2.0` and `finalhandler@2.1.1`. Repos were registered as
`express` (role code), `router` and `finalhandler` (role dep). The predict step was skipped.

| file | step |
|---|---|
| `brief.md` | study brief, from general knowledge (theory, unverified) |
| `scout.json` | where the concept lives; found that Express delegates the chain to `router` |
| `notes.md` | tagged, cited research notes, after verification |
| `verification.md` | what the verifier changed and what it ran |
| `lesson.src.md` / `lesson.md` | the lesson, before and after real code is pulled in |

Citations are version-specific: they hold for the versions above. `dl.py check` passes against them.
