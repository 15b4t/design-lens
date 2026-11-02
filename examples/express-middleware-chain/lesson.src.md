## The middleware chain in Express 5: a router's `next()` scan, not an onion

*Kind: mechanism. Where: `app.handle` (express:lib/application.js), `Router` `handle`/`next` and `Layer` (router@2.2.0), `finalhandler@2.1.1`. How sure: the chain mechanics are read from source (evidenced); consequences such as stalls and mid-request `use` are partly inferred, and body reading and double-write protection are not covered.*

### 1. You guessed, and the code says
You skipped the predict step, so there is nothing to score. The most surprising thing the notes show instead:

**A layer added with `use` while a request is in flight can run for that same request.** The router reads its `stack` array by reference and checks its length on every step (`stack` router:index.js:166-166), and `Router.use` pushes onto that same array (`use` router:index.js:388-407). The notes record a test: a middleware that calls `app.use` mid-request had the new layer run for that same request (evidenced). Your chain is not frozen after startup. It is one mutable array that every in-flight request is walking.

### 2. The textbook in one paragraph
In the textbook design (theory, not a finding), a middleware chain is an ordered list of handlers. Each one can change the request, answer it, or hand control on. Two shapes exist: a linear `next()` pipeline, and an onion where each layer wraps the rest and sees both the request going in and the response coming out. The decisions that separate implementations are where order lives, how control is passed, how a layer stops the chain, whether a layer can act on the response, how async and errors travel, and what scope a layer has.

### 3. One request, start to end
The notes' worked example is hypothetical: `app.use(logger)` then `app.get('/users', h)`, and a `GET /users`. The names are invented; the mechanics are the cited lines.

**Step 1: entry.** `app.handle` builds `done` from `finalhandler` unless the caller passed a callback:

{{excerpt express:lib/application.js:152-157}}

It then sets the prototypes of `req` and `res` to the app's request and response and creates `res.locals` (`setPrototypeOf` express:lib/application.js:168-175), and calls `this.router.handle(req, res, done)` (`handle` express:lib/application.js:177-177). Express owns no chain code here. The `router` property is a lazy getter that creates one `Router` on first read and caches it (`getrouter` express:lib/application.js:69-82). That is **D9**: the chain is built once, but it stays mutable (see section 1).

**Step 2: the scan.** The router's handle function sets `idx` to 0, takes the stack and calls `next` once (`stack` router:index.js:156-186). It also sets `req.next` to the router's `next` (`next` router:index.js:174-174), which matters in step 6. The inner `next` is the whole engine:

{{excerpt router:index.js:188-216}}

It scans forward from `idx` for the first layer whose path matches and skips the rest (`matchLayer` router:index.js:235-247). For `GET /users`, `logger` matches first. That is **D1**: order is registration order. `Router.route` pushes onto the same `stack` as `Router.use`, so routes and middleware share one ordering (`route` router:index.js:425-442). The textbook alternatives, numeric priority or a config list, do not appear in the cited code.

**Step 3: calling your function.** For a path-scoped use-layer the router strips the mount prefix from `req.url` and calls `layer.handleRequest` or `layer.handleError` (`next` router:index.js:322-343). `handleRequest` is where your code actually runs:

{{excerpt router:lib/layer.js:142-163}}

This is **D2**: `next` is the third argument (`next` router:lib/layer.js:150-152). It is a plain callback, not a wrapper around the inner handler. The function runs inside a try block (`handleRequest` router:lib/layer.js:142-152).

**Step 4: what can fail inside your function.**

- It throws synchronously. The catch sends it to `next(err)` (`next` router:lib/layer.js:128-130). This is **D6**.
- It returns a rejected promise. `ret.then(null, ...)` forwards the rejection to `next(error || new Error('Rejected promise'))` (`next` router:lib/layer.js:154-163). This is **D5**. In the textbook, async handling means awaiting the downstream; here the framework attaches a rejection handler and nothing more. A non-native promise-like still works but triggers a deprecation warning (`deprecate` router:lib/layer.js:155-158). The resolved value is ignored, so an async handler that resolves without calling `next` or responding still stalls (inferred, from the `.then(null, ...)` line).
- It neither responds nor calls `next`. This is **D3**. The exit to `done` sits inside the inner `next` (`setImmediate` router:index.js:212-216), so only a `next` call can reach it. The notes infer that the request stalls, because no timer or watchdog appears in the cited code. They did not search for a server-level timeout, so "the client waits until its own timeout" is an inference, not a measurement.

**Step 5: `h` calls `next()`.** Nothing is left to match, so `done(undefined)` runs. When `idx` is already past the end, this goes through `setImmediate` (`stack` router:index.js:213-216). The notes ran this route on the installed code and got `404 ... Cannot GET /users` (evidenced). The 404 comes from `finalhandler`, which builds the status and the `Cannot METHOD url` message when there is no error (`status` finalhandler:index.js:104-108). The route can also end early with `'route'` or `'router'` instead of an error. At router level `'route'` continues the scan and `'router'` exits the router (`setImmediate` router:index.js:189-210). Inside a route, `'route'` calls `done()` and `'router'` calls `done(err)` (`next` router:lib/route.js:119-128).

**Step 6: an error is pending.** Once `next(err)` has run, the router calls `layer.handleError` for use-layers (`next` router:index.js:339-343). Route layers do not match while an error is pending, so route handlers are skipped (`layerError` router:index.js:254-258). `handleError` is arity dispatch:

{{excerpt router:lib/layer.js:106-112}}

A function without exactly four parameters is passed over on the error path, and a function with more than three is skipped on the normal path (`handleRequest` router:lib/layer.js:142-148). That lets one `stack` carry both kinds of handler; the notes infer this is the reason for the design. Express's own response helpers also read `req.next` to continue or fail the chain from outside any layer (`next` express:lib/response.js:379-414).

**Step 7: the end of the line.** `finalhandler` takes the status from the error, else from the response (`getErrorStatusCode` finalhandler:index.js:90-100). It does nothing if there is no error and headers are already sent. If the error arrives after headers went out, it destroys the socket rather than replying:

{{excerpt finalhandler:index.js:84-123}}

The `onerror` callback that `app.handle` passes in is scheduled with `setImmediate` (`setImmediate` finalhandler:index.js:112-115; `finalhandler` express:lib/application.js:154-157).

**The decision that most changes how you should think about this system is D4.** `next` is called by the handler and returns nothing the framework waits on. The router never resumes a layer after the downstream finishes (`next` router:index.js:188-230). There is no onion and no response hook. A layer that wants to see the status code or time the full request has to wrap or listen on `res` itself, because the chain gives it no return path (inferred; no Express-side hook was found in the files read, and the response is created by Node, not the router). Your layers run in order on the way in, and after that the router's involvement is over.

### Against the textbook
| decision | the textbook | your code | how sure |
|---|---|---|---|
| D1 Order | registration order, priority, or config list | matches: registration order, routes and middleware in one `stack` | evidenced |
| D2 Continuation | `next()`, return value, or wrapping | matches: `next` as third argument, also `req.next` | evidenced |
| D3 Short-circuit | respond and skip `next`, throw, or return a response | matches: respond and do not call `next`; a layer that does neither stalls (no watchdog in the cited code) | evidenced for mechanics; the stall is inferred |
| D4 Post-processing | onion, response hooks, or none | deviates: no onion and no response hooks; layers must hook `res` themselves | evidenced for the router; the workaround is inferred |
| D5 Async | await next, callbacks, or unawaited | deviates: rejection handler attached via `.then(null, ...)`; the result is not awaited and a resolve without `next` stalls | evidenced; the stall is inferred |
| D6 Error path | 4-arity signature, try/catch, or error value | matches: separate 4-arity signature; sync throws and rejections both become `next(err)` | evidenced |
| D7 Scope | global, per-route, per-group, per-method | matches: global, path-prefix, per-route, per-method, nested routers | evidenced; the effective-chain statement is inferred |
| D8 Shared state | mutate request, context object, or locals | matches: mutate `req`/`res` plus `res.locals`; the router rewrites `req.params` and `req.route` | evidenced |
| D9 Construction time | static or dynamic | matches built-once; deviates from "static" in that the stack stays mutable at runtime | evidenced |
| D10 Body consumption | one early parser, replayable, or each layer reads | absent from the chain: body parsers are separate middleware re-exported by Express; whether a second reader gets an empty stream is not verified | evidenced for the router's absence; the second-reader question is theory, not verified against source |

### Where it bends
- **Mounted sub-apps skip their own `finalhandler`.** A callback is passed, so the sub-app skips the default `done` and the parent's `next` ends it (`mounted_app` express:lib/application.js:230-237).
- **`req.next` lets code leave the chain from outside.** `res` helpers continue or fail the chain themselves, including `res.format` (`next` express:lib/response.js:576-593) and a callback path (`next` express:lib/response.js:915-915).
- **Arity is read from `fn.length`.** A handler with default or rest parameters can report a different arity than its written form. A 4-arity function is skipped on the normal path, and a non-4-arity one on the error path (`handleRequest` router:lib/layer.js:142-148, inferred; `handleError` router:lib/layer.js:106-112, evidenced).
- **`next` is not a plain hop.** `'route'` and `'router'` are not errors, and at router level `'route'` just continues the scan (`setImmediate` router:index.js:189-210).
- **The terminal callback can run before `handle` returns.** When layers remain but none match, `done(layerError)` is called synchronously. The end-of-stack path is deferred (`done` router:index.js:275-277).
- **Stack depth is capped by a hop.** After 100 synchronous steps `next` goes through `setImmediate` to avoid deep recursion, and route dispatch has the same cap (`next` router:index.js:218-221; `next` router:lib/route.js:135-138).
- **Routers nest as layers.** The router is itself a `(req, res, next)` function (`router` router:index.js:59-61). On `OPTIONS` it wraps `done` so it can answer automatically if nothing else did (`done` router:index.js:176-180).

### Probe
**Q1.** Your auth middleware is registered after the route that serves `/admin`. What happens to a request without a token?
> **A:** The auth layer never runs for that request unless the route calls `next`. The scan walks the stack in registration order, with routes interleaved where they were registered (inferred, from `use` router:index.js:388-407 and `route` router:index.js:425-442, and the matching loop in `matchLayer` router:index.js:235-247).

**Q2.** A middleware throws inside an async function. Does the error reach your error handler, hang the request, or crash the process?
> **A:** In this version it reaches the error path: a rejected promise is forwarded to `next(error || new Error('Rejected promise'))` (`next` router:lib/layer.js:154-163). The same holds for a rejected promise from an error handler (`next` router:lib/layer.js:124-126). Express 4 did not catch rejected promises, but that is theory; the Express 4 source was not read. A thrown error with no 4-arity handler ends at `finalhandler` (`getErrorStatusCode` finalhandler:index.js:90-100).

**Q3.** A middleware forgets to call `next()` on one branch and sends nothing. What does the client see, and when?
> **A:** Nothing advances `idx`, so neither `done` nor `finalhandler` runs, and the client waits for its own timeout (inferred from `setImmediate` router:index.js:212-216 and the absence of a watchdog in the cited code). Whether a server-level timeout exists was not checked.

**Q4.** You add request-timing middleware. Where must it sit to include time spent in every other layer, and can it see the status code?
> **A:** Register it first, since order is registration order (`use` router:index.js:388-407). It cannot get the status from the chain, because the router never resumes a layer after the downstream finishes (`next` router:index.js:188-230). It has to wrap or listen on `res` itself (inferred).

**Q5.** You want a rate limiter for one route group only, and it must run after auth. Where does it attach, and what breaks if you get the order wrong?
> **A:** `Router.use` takes an optional path and defaults to `'/'`, and use-layers are prefix-matched (`use` router:index.js:362-380; `handle` router:index.js:428-432). A use-layer registered on the group's path, after the auth layer, runs only for that prefix and in that order. Routes interleave at their registration position, so a limiter registered after the group's route handlers does not run for them unless those handlers call `next` (inferred).

**Q6.** A request fails with no 4-arity handler registered anywhere. What does the client get, and what if the headers were already sent?
> **A:** `finalhandler` replies with the status from the error, else from the response (`getErrorStatusCode` finalhandler:index.js:90-100). If headers were already sent, it destroys the socket instead (`destroy` finalhandler:index.js:118-123).

### Take it elsewhere
Recognise a `next()` pipeline by three things: a shared array of handlers, a single callback that advances an index, and an exit that only that callback can reach. Then ask the D4 question first, because it decides whether timing, header injection and response logging are possible at all. Compare with Koa or Go `http.Handler` wrappers, where the same question has the opposite answer.

Exercise for your code: pick one security-relevant layer, such as auth, and list the effective chain for two of your real URLs by reading the registration order. Check whether any route is registered before it. Then check whether any of your handlers has a default or rest parameter, since arity dispatch reads `fn.length`.
