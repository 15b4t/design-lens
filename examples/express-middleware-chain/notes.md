# middleware-chain, research notes
Researched: 2026-11-02. Kind: mechanism. Repos: express, router, finalhandler. Versions: router@2.2.0 finalhandler@2.1.1 (express 5.3.0 per scout).

## Summary
- [inferred] Express holds almost no chain code of its own: `app.handle` builds one `Router` and hands it each request plus `finalhandler` as the terminal callback. Express does add a `mounted_app` wrapper for sub-apps, and its `res` helpers call `req.next` themselves (rests on Path 1-4 and Counterexamples). (evidenced)
- [inferred] The chain is a linear `next()` pipeline over an ordered array of Layers, not an onion. Order is registration order, and a layer can only see the response by hooking `res` itself (rests on D1, D2, D4). (inferred)
- [inferred] Errors travel by `next(err)` and skip every layer whose function is not 4-arity. Sync throws and rejected promises are both converted to `next(err)` (rests on D6). (inferred)
- [inferred] Body reading is not part of the chain; it is a separate middleware factory that Express only re-exports (rests on D10). (inferred)

## Worked example
Hypothetical request, traced through the cited code. The route and middleware names are invented for illustration; the mechanics are the cited lines.
- [inferred] With `app.use(logger)` then `app.get('/users', h)`, a `GET /users` request first runs `logger`, which calls `next()`, and the next scan reaches the route layer for `/users` (rests on Path 5-7). (inferred)
- [inferred] If `h` never responds and never calls `next`, no code advances `idx`; neither `done` nor `finalhandler` runs, so the client waits until its own timeout (rests on Path 6 and D3). (inferred)
- [inferred] If `h` calls `next()`, `done(undefined)` runs and `finalhandler` sends `Cannot GET /users` with status 404. When `idx` is already past the end this goes through `setImmediate`; when layers remain but none match, `done(layerError)` is called synchronously (rests on Path 6 and Failure behaviour; I ran this route on the installed code and got `404 ... Cannot GET /users`). (evidenced)

## Path
1. [code] `app.handle` is the per-request entry; it builds `done` from `finalhandler` unless a callback was passed (`handle` express:lib/application.js:152-157) (evidenced)
2. [code] It sets the prototypes of req and res to the app's request and response, and creates res.locals (`setPrototypeOf` express:lib/application.js:168-175) (evidenced)
3. [code] It then calls `this.router.handle(req, res, done)` (`handle` express:lib/application.js:177-177) (evidenced)
4. [code] The `router` property is a lazy getter that creates one `Router` the first time it is read (`getrouter` express:lib/application.js:69-82) (evidenced)
5. [dep] The router's handle function sets idx to 0, takes the stack, and calls next once to start (`stack` router:index.js:156-186) (evidenced)
6. [dep] The inner `next` ends the chain via `setImmediate(done, layerError)` when `idx` has passed the end of `stack` (`next` router:index.js:188-216) (evidenced)
7. [dep] The inner next scans forward from idx for the first layer whose path matches, skipping non-matching ones (`matchLayer` router:index.js:235-247) (evidenced)
8. [dep] For a path-scoped use-layer it strips the mount prefix from `req.url` and calls `layer.handleRequest` or `layer.handleError` (`next` router:index.js:322-343) (evidenced)
9. [dep] `Layer.handleRequest` calls the user function as `fn(req, res, next)` inside a try block (`handleRequest` router:lib/layer.js:142-152) (evidenced)

## Decisions
- **D1 Order**: matches (registration order)
  - [dep] `Router.use` appends one Layer per function with `this.stack.push`, so order is call order (`use` router:index.js:388-407) (evidenced)
  - [dep] `Router.route` pushes its layer onto the same `stack`, so routes and middleware share one ordering (`route` router:index.js:425-442) (evidenced)
  - [code] `app.use` forwards to `router.use` for a plain function (`use` express:lib/application.js:219-223) (evidenced)
  - [theory] Textbook alternatives are numeric priority or a config list; neither appears in the cited code.
- **D2 Continuation mechanism**: matches (call `next()`)
  - [dep] The handler receives `next` as its third argument (`next` router:lib/layer.js:150-152) (evidenced)
  - [dep] `req.next` is also set to the router's `next` (`next` router:index.js:174-174) (evidenced)
- **D3 Short-circuit**: matches (respond and do not call `next`)
  - [dep] The end-of-stack exit to `done` sits inside the inner next function, so only a next call can reach it (`setImmediate` router:index.js:212-216) (evidenced)
  - [inferred] A layer that neither responds nor calls `next` stalls the request, because no timer or watchdog exists in the cited code (rests on D3 line above; I did not search for a server-level timeout). (evidenced)
  - [dep] At router level `'route'` is turned into no error (the scan simply moves to the next layer), and `'router'` exits the whole router (`setImmediate` router:index.js:189-210) (evidenced)
  - [dep] Inside a route, `'route'` calls `done()` and `'router'` calls `done(err)` (`next` router:lib/route.js:119-128) (evidenced)
- **D4 Post-processing**: deviates (no onion, no response hooks)
  - [dep] `next` is called by the handler and returns nothing the framework waits on; the router never resumes a layer after the downstream finishes (`next` router:index.js:188-230) (evidenced)
  - [inferred] A layer that wants to act on the response must wrap or listen on `res` itself, since the chain gives it no return path. The response is created by Node, not the router (rests on the line above; no Express-side hook was found in the files read). (inferred)
- **D5 Async handling**: deviates (framework attaches a rejection handler; it does not await)
  - [dep] If the handler returns a promise, `ret.then(null, ...)` forwards a rejection to `next(error || new Error('Rejected promise'))` (`next` router:lib/layer.js:154-163) (evidenced)
  - [dep] Promise-like but non-native returns still work but trigger a deprecation warning (`deprecate` router:lib/layer.js:155-158) (evidenced)
  - [inferred] The resolved value is ignored, so an async handler that resolves without calling `next` or responding still stalls (rests on the `.then(null, ...)` line above). (inferred)
- **D6 Error path**: matches (separate 4-arity signature)
  - [dep] handleRequest skips any function with more than 3 parameters (`next` router:lib/layer.js:145-148) (evidenced)
  - [dep] handleError passes the error on unless the function has exactly 4 parameters (`next` router:lib/layer.js:107-112) (evidenced)
  - [dep] Once an error is pending, `next` calls `layer.handleError` for use-layers (`next` router:index.js:339-343) (evidenced)
  - [dep] Route layers do not match while an error is pending, so route handlers are skipped (`layerError` router:index.js:254-258) (evidenced)
  - [dep] A sync throw in either handler kind is caught and sent to `next(err)` (`next` router:lib/layer.js:128-130) (evidenced)
  - [dep] A rejected promise from an error handler is also forwarded to `next` (`next` router:lib/layer.js:124-126) (evidenced)
  - [theory] Express 4 did not catch rejected promises; the scout notes this and the installed 2.2.0 code does catch them. Express 4 source was not read.
- **D7 Scope**: matches (global, path-prefix, per-route, per-method, and nested routers)
  - [dep] `Router.use` defaults `path` to `'/'` and takes an optional path (`use` router:index.js:362-380) (evidenced)
  - [dep] Use-layers are built with `end: false` (prefix match) and route layers with `end: true` (exact) (`handle` router:index.js:428-432) (evidenced)
  - [dep] A route has its own stack with a method check per layer (`stack` router:lib/route.js:144-147) (evidenced)
  - [dep] A route layer is skipped when it has no handler for the method, with HEAD allowed to fall through (`hasMethod` router:index.js:260-271) (evidenced)
  - [code] A mounted express app is wrapped as a use-layer on the parent router (`mounted_app` express:lib/application.js:230-237) (evidenced)
  - [inferred] The effective chain for a URL is the global use-layers that match its prefix, in registration order, with routes interleaved at the position where they were registered (rests on D1 lines and the matching loop in Path 7). A security layer registered after a route never runs for that route's request unless the route calls `next`. (inferred)
- **D8 Shared state**: matches (mutate req and res, plus `res.locals`)
  - [code] res.locals is created per request (`locals` express:lib/application.js:173-175) (evidenced)
  - [code] req.res and res.req are cross-linked (`req` express:lib/application.js:164-166) (evidenced)
  - [dep] req.params and req.route are rewritten by the router as it walks the stack (`params` router:index.js:279-288) (evidenced)
  - [dep] `restore` saves and resets `baseUrl`, `next` and `params` on exit from a router (`next` router:index.js:171-171) (evidenced)
- **D9 Chain construction time**: matches (built once, lazily; mutable at runtime)
  - [code] The `Router` is created on first access to `this.router` and cached (`router` express:lib/application.js:73-80) (evidenced)
  - [dep] The router reads its stack by reference and checks its length on each step (`stack` router:index.js:166-166) (evidenced)
  - [inferred] Calling `use` while requests are in flight pushes onto the same array those requests are walking, so a new layer can be seen by an in-flight request that has not yet passed the end (rests on the two lines above; I ran a middleware that calls `app.use` mid-request and the new layer ran for that same request). (evidenced)
- **D10 Body and stream consumption**: absent from the chain; separate middleware
  - [code] Express exports body parsers by re-exporting `body-parser` factories (`bodyParser` express:lib/express.js:77-81) (evidenced)
  - [inferred] Nothing in the router reads or buffers the body, so layers that do so are ordinary middleware (rests on Path 5-9, where no body access appears). (evidenced)
  - [theory] Whether a second reader gets an empty stream is a property of `body-parser` and Node streams. `body-parser` is not a registered repo here. Reading `node_modules/body-parser/lib/read.js` would settle it.

## Failure behaviour
- [dep] When no layer remains, `done` receives any pending error; with none it is a 404 (`stack` router:index.js:213-216) (evidenced)
- [dep] When layers remain but none match, `done(layerError)` is called synchronously, not deferred (`done` router:index.js:275-277) (evidenced)
- [dep] finalhandler returns without doing anything if there is no error and headers are already sent (`headersSent` finalhandler:index.js:84-87) (evidenced)
- [dep] With no error, finalhandler builds a 404 and a Cannot-METHOD-url message (`status` finalhandler:index.js:104-108) (evidenced)
- [dep] With an error, finalhandler takes the status from the error, else from the response (`getErrorStatusCode` finalhandler:index.js:90-100) (evidenced)
- [dep] The onerror callback is scheduled with `setImmediate` (`setImmediate` finalhandler:index.js:112-115) (evidenced)
- [dep] If headers are already sent when the error arrives, finalhandler destroys the socket instead of replying (`destroy` finalhandler:index.js:118-123) (evidenced)
- [code] app.handle passes an onerror callback and the app env to finalhandler (`finalhandler` express:lib/application.js:154-157) (evidenced)
- [dep] An unparseable URL ends the chain through `done(layerError)` (`getPathname` router:index.js:478-484) (evidenced)
  - [dep] A path that throws in the matcher is returned as an error value and held as the pending error (`layerError` router:index.js:240-243) (evidenced)
- [dep] Param callbacks that fail pass the error on to `next` (`processParams` router:index.js:291-293) (evidenced)
- [inferred] Double write: no guard against a second `res.send` was found in the files read. `finalhandler` only protects its own write. Whatever stops a second write comes from Node's header-sent check, which I did not verify (rests on the lines above). (inferred)

## Design reasons
- [dep] `next` hops through `setImmediate` after 100 synchronous steps to avoid deep synchronous recursion (`next` router:index.js:218-221) (evidenced)
- [dep] Route dispatch has the same 100-step cap (`next` router:lib/route.js:135-138) (evidenced)
- [dep] The router is itself a (req, res, next) function, so routers nest as ordinary layers (`router` router:index.js:59-61) (evidenced)
- [dep] On `OPTIONS`, the router collects methods and wraps `done` so it can answer automatically if nothing else did (`done` router:index.js:176-180) (evidenced)
- [inferred] The arity-based error signature lets one `stack` carry both normal and error handlers without separate lists (rests on D6 lines). (inferred)

## Counterexamples
- [code] A mounted sub-app is not run through its own finalhandler: a callback is passed, so the sub-app skips the default done and the parent's next ends it (`mounted_app` express:lib/application.js:230-237) (evidenced)
- [code] Express's own response helpers read req.next to continue or fail the chain from outside any layer's next argument (`next` express:lib/response.js:379-414), including res.format (`next` express:lib/response.js:576-593) and a callback path (`next` express:lib/response.js:915-915) (evidenced)
- [dep] Dispatch is by fn.length, so a handler declared with default or rest parameters can report a different arity than its written form; a 4-arity function is skipped on the normal path and a non-4-arity one on the error path (`handleRequest` router:lib/layer.js:142-148) (inferred)
- [dep] The error-path half of the same arity dispatch (`handleError` router:lib/layer.js:106-112) (evidenced)
- [dep] The "next hops through the list" model bends at `'route'` and `'router'`: they are not errors, and at router level 'route' just continues the scan (`setImmediate` router:index.js:189-210) (evidenced)
- [dep] A sync `done(layerError)` on a no-match scan means the terminal callback can run before the call to handle returns, unlike the end-of-stack path (`done` router:index.js:275-277) (evidenced)

## Dependencies
- router@2.2.0: all chain mechanics (ordering, `next`, arity dispatch, promise capture, scope). Source read in full for the relevant functions.
- finalhandler@2.1.1: terminal 404 and error response, socket destroy when headers are sent. Source read.
- body-parser: re-exported at `express:lib/express.js`; its source was not registered or read beyond a grep, so no claim about it is made above.

## Open questions
- Does a second body reader receive an empty stream? Read `node_modules/body-parser/lib/read.js` and its types to settle D10.
- What stops a double `res.send` on this version? Read `lib/response.js` `send` and Node's `ERR_HTTP_HEADERS_SENT` path.
- Is there a server-level timeout for a stalled request? Check `app.listen` and Node server defaults, outside this concept.
- Does `processParams` (router.param) count as chain behaviour? It was left out as route-matching related.
