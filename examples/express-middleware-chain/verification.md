# middleware-chain verification
Ran: re-read router index.js/layer.js/route.js, express application.js/express.js, finalhandler index.js against cited ranges; greps for `timeout`, body access (`req.on|pipe|body|stream`), `headersSent` in lib, `next` in lib; a node script on installed express 5.3.0 / router 2.2.0 (404 on `next()` from last route, async throw reaching a 4-arity handler, `app.use` mid-request seen by that request).

- Summary 1 "Express itself holds no chain code" -> corrected - found `mounted_app` wrapper and `req.next` uses in `lib/response.js`; reworded to "almost no"
- Worked example 3 "done runs via setImmediate" -> corrected - `index.js:275-277` calls `done(layerError)` synchronously when layers remain but none match; setImmediate only at end-of-stack. 404 body confirmed by running it
- D3 `'route'` line (router:index.js:206-210) -> corrected - those lines only handle `'router'`; `'route'` is nulled at 189-191 and the scan continues
- D9 in-flight `use` claim -> confirmed (was "not tested") - ran it; new layer ran for the same request, now (evidenced)
- Failure behaviour -> added line for synchronous no-match `done`
- Added `## Counterexamples` (5 lines)
- D3 no-timeout and D10 no-body-access negative claims -> confirmed - grep returned nothing in express lib, router, finalhandler (scoped to those files; server-level timeouts not examined)
- Double-write claim -> left (inferred); grep of lib shows `headersSent` only in comments, Node's check unverified

Confirmed without change: 60 evidence lines (all cited ranges matched; versions router 2.2.0, finalhandler 2.1.1, express 5.3.0 confirmed from package.json). Central claim (linear next() pipeline, arity-based errors) held.
