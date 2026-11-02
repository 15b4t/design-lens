# Dogfood 1: Express middleware chain

First full run of the pipeline (brief, scout, research, verify, teach) on real code. Output is in
`examples/express-middleware-chain/`.

## What worked

- The scout found that Express 5 contains almost no chain code: the mechanism lives in the installed
  `router` dependency. `[dep]` evidence and `DL deps` were needed for this and worked.
- The verifier found real errors: a wrong timing claim in the 404 path (`done` is synchronous when layers
  remain but none match; `setImmediate` only at end-of-stack), an overclaim ("holds no chain code"), and a
  citation that covered `'router'` but not `'route'`. It also ran the installed code. Spot-checked
  independently against source: all three held.
- It added five counterexamples (mounted sub-apps, `req.next` used by response helpers, arity dispatch,
  the sentinel values, the sync no-match path), which became the lesson's "Where it bends".

## Bugs found in design-lens itself

Fixed:
- `check` held every backticked word on a lesson line to the cited range: 16 false positives on a
  correct lesson. Now each citation is checked against its own preceding symbol.
- Nothing enforced "never teach unchecked": a chained command marked a failing lesson `taught`. `mark`
  now refuses `verified`/`taught` while `check` fails.

Open:
1. **Verifier brief: confidence words on `[inferred]` lines.** Several `[inferred]` lines were labelled
   `(evidenced)`. Inferences should be `(inferred)` by definition.
2. **Verifier brief: "deviates" was never challenged.** D4/D5 are marked `deviates`, but the brief itself
   lists the Express-style `next()` pipeline as a textbook shape. A deviation from *a* textbook is not a
   deviation from *the* textbook. The verifier should test the label, not only the evidence.
3. **Symbol check is weak for generic names.** `status`, `req`, `params` pass trivially in any range.
   Consider rejecting a short list of generic symbols, or requiring the symbol on a definition line.
4. **Library as subject.** The worked example was hypothetical (a library has no real request) and the
   lesson says "your" about a library. The lesson guide needs a rule for studying a dependency or
   framework itself.
5. **`DL search` is flooded by test files** as `fingerprint` was. Skip or down-rank them by default.
6. **`fingerprint` false positive:** `lib/response.js:379` is reported as a linked list because of
   `var next = req.next`. The traversal pattern should require assignment from a `.next` of the same variable.
7. **Brief leftover:** the briefer wrote `(mechanism: section deleted.)` instead of omitting the section.
8. Predict was skipped, so the lesson's opening section had to improvise. Not a bug, but the
   lesson guide should say what to do when there are no predictions.

## Not established

Whether the lesson teaches well. That needs a reader who is learning it.
