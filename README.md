# design-lens

A Claude Code skill for learning system design from the codebases you actually work on.

You learn a concept in theory: a message queue, Redis pub/sub, union-find, a notification system. The
skill then finds out how *your* code does it (or doesn't), checks that finding against the code, and
teaches it with your real code quoted, compared against the textbook.

## What it does

```
/design-lens message queue           learn a concept: predict, see the code, compare to theory, get probed
/design-lens how redis pub/sub works technology internals, and where your code relies on them
/design-lens union find              a data structure, found by its shape even if hand-rolled
/design-lens explain src/cache/x.go  you saw something in the code and want its name
/design-lens discover api            what in this repo is worth learning, ranked
/design-lens quiz                    questions about your own code, from what you've already learned
/design-lens stale                   learned concepts whose code has since changed
```

A concept is one of five kinds, and the kind decides the lesson's shape:

| kind | examples |
|---|---|
| mechanism | message queue, caching, retries |
| algorithm | a graph algorithm in your domain |
| structure | union-find, LRU, trie, ring buffer |
| system | a notification system |
| internals | how Redis pub/sub or a client library works |

## The loop

1. **Brief**: a checklist of the decisions theory says matter, from your study material if you give
   it, otherwise from general knowledge labelled as unverified theory. You correct it.
2. **Predict**: you answer 2-4 questions about your code before seeing anything.
3. **Scout**: finds where the concept lives, rules out look-alikes (a `queue` in a BFS is not a message
   queue), or reports that it isn't there.
4. **Research**: reads the code (and installed dependency source) and writes cited, tagged notes.
5. **Verify**: a separate agent tries to disprove every claim, and records where the concept does *not* hold.
6. **Teach**: a lesson with real code pulled in by script, a table against the textbook, and probe questions.

## Why you can trust a lesson

- Every claim is tagged by source: `[code]` your repo, `[dep]` installed dependency source,
  `[upstream]` the technology's own source, `[theory]` background knowledge, `[inferred]`.
  Theory is never presented as what your code does.
- `scripts/dl.py check` verifies each evidence claim mechanically: the file exists, the range is short,
  and a named symbol appears *inside the cited range*, not merely near it.
- Code in a lesson is pulled from source by script and re-verified, so it can't be retyped wrong, and a
  quote that no longer matches the file is flagged.
- Technology internals are checked against the version your lockfile actually installs.
- "Not here" is a valid result.

## Your code stays yours

The notebook lives in `~/system-design-notebook` (override with `--home` or `$DL_HOME`), and the script
refuses to put it inside a repo you study. Nothing is written into your work repos. Check that your
employer permits AI tools on that code.

## Install

```sh
git clone https://github.com/15b4t/design-lens ~/.claude/skills/design-lens
```

Needs python3 (standard library only). Restart Claude Code and run `/design-lens`. Register the repos
you study once:

```sh
python3 ~/.claude/skills/design-lens/scripts/dl.py repo add api ~/work/api
python3 ~/.claude/skills/design-lens/scripts/dl.py repo add redis-client ~/work/api/node_modules/ioredis --role dep
```

## Layout

```
SKILL.md                    orchestration
scripts/dl.py               repos, search, deps, structure fingerprints, checks, excerpts, staleness
references/brief-guide.md   study brief
references/scout-brief.md   find it, or establish it isn't there
references/research-brief.md   cited, tagged notes
references/verifier-brief.md   try to disprove them
references/lesson-guide.md  the lesson, per kind
tests/test_dl.py            python3 -m unittest discover -s tests
```

## Limits

- Structure fingerprints are heuristics: a match is a lead the scout must confirm, and a hand-rolled
  structure with an unusual shape can be missed.
- The verifier is a second model pass, not a proof. Labels (`stated` / `evidenced` / `inferred`) say how
  hard it looked, not that it is certain.
- A technology's behaviour is only verified if its source is available (`--role dep|upstream`); otherwise
  those parts are marked unverified in the lesson.
