---
name: design-lens
description: Teach system design from the user's own working codebase. Use when the user wants to understand how a concept is actually implemented in the code they work on or its dependencies - a mechanism (message queue, caching, retries), an algorithm (a graph algorithm), a data structure (union-find, LRU, trie, ring buffer), a whole feature (a notification system), or a technology's internals (how Redis pub/sub works). Triggers on "how do we use X", "where is X in our code", "show me X in a real codebase", "what is this data structure/pattern", "what should I learn from this codebase", "I just learned about X", or a request to quiz or refresh what they have learned.
argument-hint: "[<concept> | explain <path> | discover [repo] | quiz [concept] | status | stale | refresh <concept> | repo add|list]"
---

# design-lens

The user learns system design by studying the codebases they work on. They learn a concept in theory;
this skill finds out how their real code does (or doesn't) apply it, checks that finding against the
code, and teaches it with the actual code quoted. One concept at a time, interactive, with a personal
notebook that remembers what they have learned and notices when the code underneath has changed.

The audience is one engineer learning on their own work code (JS/TS, Go, some C; backend, React, Vue).
Wrong teaching is worse than none: they cannot tell, and they will repeat it in design discussions. So
every claim about their code is verified by something other than the step that made it.

## Rules

1. **You (the orchestrator) never read source code.** `DL` scripts search it, subagents read it, and you
   read only their short replies and script output. This keeps cost flat however big the repo is.
2. **Theory is never evidence.** Everything is tagged by where it comes from: `[code]` their repo,
   `[dep]` installed dependency source, `[upstream]` the technology's own source or docs, `[theory]`
   general knowledge, `[inferred]` a conclusion drawn from the others. Never present a `[theory]` line as
   what their code does. Never teach before `DL check` passes and the verifier has run.
3. **"Not here" is a valid answer.** If the concept is absent, or the code does something different,
   say so plainly and offer the nearest real thing. Never bend the code to fit the textbook.
4. **The user predicts before they see.** Skip it only if they ask. Their wrong guesses are the most
   useful data in the whole session.
5. **Their code stays theirs.** The notebook lives outside every repo studied (`DL repo add` refuses
   otherwise). Never write notes into a work repo. On the first session, say once, in a line, that they
   should be sure their employer permits AI tools on this code; then move on.
6. **Don't read the brief files yourself.** Pass their paths to the subagents.
7. **Mechanical work goes through `DL`**: search, deps, structure fingerprints, excerpts, citation
   checks, staleness. Code in a lesson is pulled by `DL expand`, never retyped.

`DL` means `python3 <this skill's dir>/scripts/dl.py`. Notebook default `~/system-design-notebook`
(`--home` or `$DL_HOME` to change it).

## Subagent models

| step | model | why |
|---|---|---|
| briefer, scout, researcher | `sonnet` | mostly search and targeted reads, verified afterwards |
| verifier | `inherit` | the one step that must be sharper than the author it checks |
| teacher | `inherit` | the prose is the product |

If the user names a different model, use it. For `inherit`, omit the Agent tool's `model` parameter.

## Concept kinds

Classify the concept first; the kind decides the shape of the brief, the research and the lesson. Ask
only if two kinds are genuinely plausible.

| kind | examples | the lesson is about |
|---|---|---|
| `mechanism` | message queue, caching, retries, rate limiting | the decisions theory says matter, answered from their code |
| `algorithm` | a graph algorithm, consistent hashing | what the inputs mean in their domain, why this one, cost at their real sizes |
| `structure` | union-find, LRU, trie, ring buffer, heap | operations and cost, the invariant, what it replaced, whether the textbook guarantee holds |
| `system` | a notification system, search, auth flow | components and one real request across layers, compared to a reference design |
| `internals` | how Redis pub/sub works, how a client library retries | how the technology works, then where their code relies on it - and where it assumes wrongly |

## Commands

- **a concept** (`message queue`, `how we do notifications`, `union find`): **Learn**.
- `explain <path>`: **Explain**, the other direction - they saw something in the code and want its name.
- `discover [repo]`: **Discover**, what is worth learning here.
- `quiz [concept]`: **Quiz**, from the notebook, using their own code.
- `status`: `DL status`. `stale`: `DL stale`. `repo add|list|remove`: `DL repo ...`.
- `refresh <concept>`: **Refresh**.
- no argument: `DL status`; if empty, **Setup**, then ask what they just learned or want to learn.

## Setup

`DL repo list`. If nothing is registered, ask which repos to study (path, short alias; free text is
fine) and run `DL repo add <alias> <path>` for each. Roles: `code` (their repos, the default), `dep`
(dependency source read in place), `upstream` (the technology's own source, e.g. a clone of a Redis or
Kafka client). Aliases are what citations use: `api:src/queue/worker.ts:40-62`.

## Learn

1. **Classify** the concept (table above) and pick a slug. If the concept spans repos, name them all.
2. **Brief.** If the user gave study material (a link, a paste, a path), tell the briefer to build the
   checklist from it. Otherwise from general knowledge, which stays `[theory]`. Spawn `models.briefer`:
   "Read `<skill>/references/brief-guide.md` and follow it. Concept: `<concept>`. Kind: `<kind>`. Study
   material: `<paths or none>`. Write `<home>/concepts/<slug>/brief.md`." Then show the user the
   checklist of decisions in a few lines and ask if it matches what they learned; fix it with them if
   not. They know their own source better than any default. Run `DL concept new <slug> --kind <k> --repo
   <aliases>` before the briefer writes, then `DL mark <slug> --status briefed` after.
3. **Predict.** From the brief's questions, ask the user 2-4 about *their* code in one message ("What
   happens to a job if the worker crashes after handling but before acking?"). Wait. Save their answers
   verbatim to `<home>/concepts/<slug>/predictions.md`. Don't comment on them yet.
4. **Scout.** Spawn `models.scout`: "Read `<skill>/references/scout-brief.md` and follow it. Concept:
   `<slug>`. Kind: `<kind>`. Brief: `<path>`. Repos: `<DL repo list>`. `DL` is `<command>`." It replies
   with JSON: where the concept lives, which dependencies carry it (with installed versions), or
   `"present": false`. If absent, stop and tell the user: say what you searched, name the nearest
   thing found, and ask whether to learn that instead.
5. **Source plan (internals, and any concept resting on a dependency).** If the scout reports that
   behaviour lives in a dependency, ask the user where its source is or offer to register what
   `DL deps` located (`DL repo add <alias> <path> --role dep`). For a technology's own behaviour
   (Redis, a broker) ask for a checkout of it (`--role upstream`). If none is available, the researcher
   marks those parts `[theory]` and the lesson says they are unverified. Never pass memory off as source.
6. **Research.** Spawn `models.researcher`: "Read `<skill>/references/research-brief.md` and follow
   it. Concept: `<slug>`. Kind: `<kind>`. Brief: `<path>`. Scout result: `<json>`. Notes:
   `<home>/concepts/<slug>/notes.md`. `DL` is `<command>`." Wide concepts (a whole system) may split
   across up to 3 parallel researchers by component; each writes its own section file the lead merges.
   Then `DL check <slug>`; if it fails, have the researcher fix or drop the failing claims (one round).
   `DL mark <slug> --status researched`.
7. **Verify.** A fresh subagent, `models.verifier`: "Read `<skill>/references/verifier-brief.md` and
   follow it. Concept: `<slug>`. Notes: `<path>`. `DL` is `<command>`." It tries to disprove each claim
   and each deviation from the brief's checklist, then rewrites the notes with verdicts and labels. Run
   `DL check <slug>` again. If the verifier removed the central claim, tell the user the concept is not
   what it looked like and say what is. `DL mark <slug> --status verified`.
8. **Teach.** Spawn `models.teacher`: "Read `<skill>/references/lesson-guide.md` and follow it.
   Concept: `<slug>`. Kind: `<kind>`. Brief, notes, predictions: `<paths>`. Write
   `<home>/concepts/<slug>/lesson.src.md`." Then `DL expand <slug>` and `DL check <slug>`.
9. **Walk them through it.** Present the lesson in two or three parts, not one wall of text, and start
   with how their prediction compared to what is true. Then run the lesson's **Probe** questions one at
   a time: ask, wait for their answer, then give the answer from the lesson with its citation. Point
   them to `lesson.md` (real code quoted) to keep.
10. **Capture.** Append to `<home>/concepts/<slug>/journal.md`: date, what they predicted, what was true,
    and which probe questions they got wrong. `DL mark <slug> --status taught`.

## Explain

They point at a file, function or snippet. Spawn `models.scout` with `references/scout-brief.md`, told
this is the reverse direction: name the concept behind the code (structure, mechanism, algorithm) with
confidence and the nearest alternatives it could be, citing what in the code gave it away. Report in a
few lines and offer to run **Learn** on it. State a guess as a guess.

## Discover

`DL fingerprint <alias>` and `DL deps <alias>`, then spawn `models.scout`: "Read
`<skill>/references/scout-brief.md`; this is a discovery run: propose concepts worth learning in
`<alias>`, from the fingerprint output and dependency list." Report a ranked list of 5-8: concept, kind,
where it lives, why it is worth learning, and the confidence that it really is what it looks like. Say
which are strong leads and which are shape-matches only. Ask which to start.

## Quiz

Pick a `taught` concept (the one named, else the oldest, skipping any `DL stale` flags unless asked).
From its `notes.md` and `journal.md` only, ask 3 questions about *their* code: a prediction ("what
happens if..."), a recognition ("which of these is the ack?"), a design question ("why not X here?").
One at a time. Answer from the notes with the citation. Weight toward what the journal says they got
wrong. Do not read code to quiz.

## Refresh

`DL stale <slug>` lists cited files that changed. Spawn the researcher in refresh mode with the changed
files only (it updates `notes.md` in place), then verify, `DL expand`, `DL check`, `DL mark`. Tell the
user in two lines what changed in how their system works, not that the notes were updated.

## Never

Present theory as their code. Teach from unchecked notes. Retype code instead of `DL expand`. Put the
notebook inside a repo. Claim a library behaves a certain way without the installed source or docs for
the installed version. Skip the verifier because the researcher "seemed sure".
