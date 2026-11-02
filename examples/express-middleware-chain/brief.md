# middleware chain, study brief
Kind: mechanism. Source: general knowledge (background theory, unverified). Every line below is background theory, not a finding about anyone's code.

## What it is
A middleware chain passes a request through an ordered list of handlers. Each handler can inspect or change the request, produce a response itself, or hand control to the next handler. This lets cross-cutting work (logging, auth, parsing, error handling, compression) live apart from business logic and be composed in a chosen order. Two shapes exist: a linear "next()" pipeline (Express-style), and a nested "onion" where each layer wraps the rest and sees both the request going in and the response coming out (Koa, Go `http.Handler` wrappers).

## Decisions that matter
- **D1 Order**: Where is the order defined, and is it explicit (registration order) or computed (priority numbers, dependency sorting)? Options: registration order / numeric priority / declarative list in config. Why it matters: auth placed after the route handler, or body parsing after the code that reads the body, silently breaks things.
- **D2 Continuation mechanism**: How does a handler pass control on? Options: call `next()` / return a value and let the framework continue / wrap the inner handler as a function. Why it matters: it decides whether code can run after the downstream finishes.
- **D3 Short-circuit**: How does a handler stop the chain (reply without calling next)? Options: send response and don't call next / throw / return a response object. Why it matters: forgetting to stop leads to double responses or a handler running after auth failed.
- **D4 Post-processing**: Can a layer act on the response on the way back? Options: onion (code after next) / separate response hooks / not at all. Why it matters: timing, header injection and response logging depend on it.
- **D5 Async handling**: How are async handlers awaited? Options: await next / callbacks / unawaited promises. Why it matters: an unawaited next lets the chain finish early, and errors escape.
- **D6 Error path**: How do errors travel? Options: separate error-handler signature / try/catch around next / error value returned. Why it matters: an error thrown in async code may bypass the handler and crash or hang the request.
- **D7 Scope**: Is a middleware global, per-route, per-group, or per-method? Options: all four, or a subset. Why it matters: the effective chain for an endpoint may differ from the global one, so a security check can be absent on one route.
- **D8 Shared state**: How do layers pass data along? Options: mutate the request / context object / typed context keys / locals. Why it matters: name collisions and untyped keys cause hidden coupling.
- **D9 Chain construction time**: Is the chain built once at startup or per request? Options: static / dynamic. Why it matters: per-request building costs time, and runtime changes can race with in-flight requests.
- **D10 Body and stream consumption**: Who reads the body, and can it be read twice? Options: one parser early / buffered and replayable / each layer reads. Why it matters: a stream consumed by a logging layer leaves nothing for the handler.

## Search vocabulary
- JS/TS: `app.use`, `router.use`, `next`, `next(err)`, `(err, req, res, next)`, `compose`, `koa-compose`, `ctx`, `express`, `koa`, `fastify` hooks (`onRequest`, `preHandler`), `NestJS` guards/interceptors/pipes, `Hono`, `middleware`, `interceptor`.
- Go: `http.Handler`, `http.HandlerFunc`, `func(next http.Handler) http.Handler`, `chi.Use`, `gin.Context.Next`, `Abort`, `alice`, `negroni`, gRPC `UnaryInterceptor`, `ChainUnaryInterceptor`.
- C: `filter chain`, `handler` function-pointer arrays, nginx phases and `ngx_http_next_header_filter`, Apache hooks/modules.
- Frontend (React/Vue): Redux `applyMiddleware`, `store.dispatch` wrappers, axios `interceptors`, Vue Router `beforeEach` / navigation guards, fetch wrappers, RTK Query `prepareHeaders`.
- Config and infra: nginx `location` and filters, Envoy `http_filters`, API gateway plugins, Traefik `middlewares`, ingress annotations, Kong plugins and priorities, service-mesh filters.

## Probe questions
1. Your auth middleware is registered after the route that serves `/admin`. What happens to a request without a token?
2. A middleware throws inside an async function. Does the error reach your error handler, hang the request, or crash the process?
3. A middleware forgets to call `next()` on one branch and sends nothing. What does the client see, and when?
4. You add request-timing middleware. Where must it sit to include time spent in every other layer, and can it see the status code?
5. Traffic grows tenfold. Which layers do work on every request (parsing, DB lookups, logging) and which could be skipped for static or health-check paths?
6. You need to add a rate limiter for one route group only. Where does it attach, and what order relative to auth?
7. Two middlewares both read the request body. What does the second one receive?
8. A layer responds early and then a later layer also writes a response. What stops the double write?

## Reference shape
(mechanism: section deleted.)

## Look-alikes
- A plain array of functions called in a `for` loop is not a chain unless each can stop or wrap the rest.
- Event emitters or pub/sub: all listeners fire, none can veto or wrap the others.
- Decorators/HOCs on a single function are wrapping, but only a middleware chain when composed over a shared request lifecycle.
- A promise `.then()` chain transforms a value; it has no request/response pair and no short-circuit by design.
- Redux reducers composed together are not middleware; `applyMiddleware` wrappers around `dispatch` are.
- Route matching (which handler runs) is not middleware (what runs around it), though frameworks often blend the two APIs.
- Lifecycle hooks (`onRequest`, `preHandler`) have a fixed phase order, which is related but not a free-form ordered chain `(verify against installed version)`.
