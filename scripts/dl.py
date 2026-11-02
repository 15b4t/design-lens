#!/usr/bin/env python3
"""dl.py: mechanical helpers for the design-lens skill. Standard library only.

The skill reasons about code; this script does everything that can be checked by machine:
registering repos, searching, finding data structures by their shape, pulling verbatim code
excerpts, verifying that notes cite real code, and noticing when cited code has changed.

State lives in a notebook directory outside any work repo (default ~/system-design-notebook,
override with --home or $DL_HOME):

    repos.json                       alias -> {path, role}
    concepts/<slug>/meta.json        kind, title, repos, status, hashes of cited files
    concepts/<slug>/brief.md         study brief (what theory says matters)
    concepts/<slug>/notes.md         tagged, cited fact sheet
    concepts/<slug>/lesson.src.md    lesson with {{excerpt alias:path:a-b}} placeholders
    concepts/<slug>/lesson.md        the lesson with real code pulled in (dl.py expand)
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time

SKIP_DIRS = {".git", "node_modules", "vendor", "dist", "build", "out", "target", ".next", ".nuxt",
             "__pycache__", ".venv", "venv", "coverage", ".cache", ".turbo"}
CODE_EXT = {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".vue", ".go", ".c", ".h", ".cc", ".cpp", ".hpp"}
LANG = {".js": "js", ".jsx": "jsx", ".mjs": "js", ".cjs": "js", ".ts": "ts", ".tsx": "tsx", ".vue": "vue",
        ".go": "go", ".c": "c", ".h": "c", ".cc": "cpp", ".cpp": "cpp", ".hpp": "cpp", ".py": "python",
        ".rs": "rust", ".java": "java", ".json": "json", ".yml": "yaml", ".yaml": "yaml", ".sh": "bash"}
ROLES = ("code", "dep", "upstream")
KINDS = ("mechanism", "algorithm", "system", "internals", "structure")
STATUSES = ("new", "briefed", "researched", "verified", "taught")
TAGS = ("code", "dep", "upstream", "theory", "inferred")
TAG_RX = re.compile(r"\[(code|dep|upstream|theory|inferred)\]")
CITE_RX = re.compile(
    r"`?([A-Za-z0-9_-]+):((?:[\w.@+-]+/)*[\w.@+-]+\.\w+):(\d+)(?:-(\d+))?`?")
SYM_RX = re.compile(r"`([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*(?:\(\))?)`")
QUOTE_RX = re.compile(r"<!--\s*quote\s+(\S+)\s*-->[ \t]*\n```[^\n]*\n(.*?)\n```", re.S)
EXCERPT_RX = re.compile(r"\{\{\s*excerpt\s+(\S+?)\s*\}\}")


def die(msg):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(2)


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


# ---------------------------------------------------------------------------------------------
# notebook state
# ---------------------------------------------------------------------------------------------

def home_dir(args):
    return os.path.abspath(os.path.expanduser(
        getattr(args, "home", None) or os.environ.get("DL_HOME") or "~/system-design-notebook"))


def load_json(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except json.JSONDecodeError as e:
        # Never fall back to a default here: the caller would overwrite a file it could not read.
        die(f"{path} is not valid JSON ({e}); fix or remove it by hand")


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")
    os.replace(tmp, path)


def load_repos(home):
    return load_json(os.path.join(home, "repos.json"), {})


def concept_dir(home, slug):
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", slug):
        die(f"concept id {slug!r} must be kebab-case (letters, digits, hyphens)")
    return os.path.join(home, "concepts", slug)


def load_concept(home, slug):
    d = concept_dir(home, slug)
    meta = load_json(os.path.join(d, "meta.json"))
    if meta is None:
        die(f"no concept {slug!r}; create it with: dl.py concept new {slug} --kind K --repo ALIAS")
    return d, meta


# ---------------------------------------------------------------------------------------------
# references: alias:path:start-end
# ---------------------------------------------------------------------------------------------

def parse_ref(ref):
    m = CITE_RX.fullmatch(ref.strip("`"))
    if not m:
        die(f"{ref!r} is not a reference; expected alias:path/to/file.ext:START-END")
    a = int(m.group(3))
    return m.group(1), m.group(2), a, int(m.group(4) or a)


def resolve(repos, alias, path):
    """Absolute path of `path` inside the repo registered as `alias`, or None if it escapes the root."""
    if alias not in repos:
        return None
    root = os.path.abspath(repos[alias]["path"])
    full = os.path.normpath(os.path.join(root, path))
    if full != root and not full.startswith(root + os.sep):
        return None
    return full


def read_lines(full, cache):
    if full not in cache:
        try:
            with open(full, errors="replace") as f:
                cache[full] = f.read().splitlines()
        except OSError:
            cache[full] = None
    return cache[full]


def sha1(full):
    h = hashlib.sha1()
    with open(full, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def normalize_block(lines):
    """Compare code ignoring trailing space, common indentation and surrounding blank lines."""
    lines = [l.rstrip() for l in lines]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    indents = [len(l) - len(l.lstrip()) for l in lines if l]
    cut = min(indents) if indents else 0
    return [l[cut:] for l in lines]


def has_symbol(text, sym):
    return re.search(r"(?<![\w$])" + re.escape(sym) + r"(?![\w$])", text) is not None


# ---------------------------------------------------------------------------------------------
# check: do the notes cite real code, honestly tagged?
# ---------------------------------------------------------------------------------------------

def check_line(line, repos, cache, max_range, require_tag=True):
    """Problems on one line of notes. A line that makes a claim about evidence carries one tag:
    [code] (the work repo), [dep] (installed dependency source), [upstream] (the technology's own
    source), [theory] (background knowledge, never proof) or [inferred]. A tagged evidence line must
    cite code of the matching role, name at least one symbol, and that symbol must appear inside the
    cited range itself - not near it."""
    tags = TAG_RX.findall(line)
    cites = list(CITE_RX.finditer(line))
    known = [m for m in cites if m.group(1) in repos]
    problems = []
    if len(set(tags)) > 1:
        problems.append(f"more than one evidence tag ({', '.join(sorted(set(tags)))}); split the claim")
        return problems
    tag = tags[0] if tags else None
    if tag is None:
        if known and require_tag:
            problems.append("cites code but carries no evidence tag ([code], [dep], [upstream], ...)")
        return problems
    if tag in ("theory", "inferred"):
        if tag == "theory" and known:
            problems.append("[theory] line cites code; retag it [code]/[dep]/[upstream] or drop the citation")
        return problems
    if not cites:
        return [f"[{tag}] claim has no alias:path:line citation"]
    ranges, text_parts = 0, []
    for m in cites:
        alias, path = m.group(1), m.group(2)
        a = int(m.group(3))
        b = int(m.group(4) or a)
        if alias not in repos:
            problems.append(f"unknown repo alias {alias!r} (register it with: dl.py repo add)")
            continue
        role = repos[alias].get("role", "code")
        if role != tag:
            problems.append(f"[{tag}] claim cites {alias!r}, which is registered as role {role!r}")
        full = resolve(repos, alias, path)
        if full is None:
            problems.append(f"{alias}:{path} escapes the repo root")
            continue
        src = read_lines(full, cache)
        if src is None:
            problems.append(f"{alias}:{path} does not exist")
            continue
        if a < 1 or b > len(src) or a > b:
            problems.append(f"{alias}:{path}:{a}-{b} out of range (file has {len(src)} lines)")
            continue
        if b - a + 1 > max_range:
            problems.append(f"{alias}:{path}:{a}-{b} spans {b - a + 1} lines (max {max_range}); "
                            "a range that wide proves nothing, narrow it")
            continue
        ranges += 1
        text_parts.append("\n".join(src[a - 1:b]))
    syms = []
    for s in SYM_RX.findall(line):
        s = s[:-2] if s.endswith("()") else s
        s = s.split(".")[-1]
        if len(s) >= 3:
            syms.append(s)
    if not syms:
        problems.append(f"[{tag}] claim names no symbol in backticks, so nothing can be verified")
    elif ranges:
        body = "\n".join(text_parts)
        missing = [s for s in syms if not has_symbol(body, s)]
        if missing:
            problems.append(f"symbol(s) {missing} not found inside the cited range(s)")
    return problems


def check_quotes(text, repos, cache):
    """Every quote block must equal the real lines it claims to come from."""
    problems = []
    for m in QUOTE_RX.finditer(text):
        ref, body = m.group(1), m.group(2)
        alias, path, a, b = parse_ref(ref)
        full = resolve(repos, alias, path)
        src = read_lines(full, cache) if full else None
        line_no = text.count("\n", 0, m.start()) + 1
        if src is None:
            problems.append(f"line {line_no}: quote source {ref} not found")
            continue
        if a < 1 or b > len(src) or a > b:
            problems.append(f"line {line_no}: quote {ref} out of range (file has {len(src)} lines)")
            continue
        if normalize_block(body.split("\n")) != normalize_block(src[a - 1:b]):
            problems.append(f"line {line_no}: quote does not match {ref} (code changed, or it was retyped)")
    return problems


def cmd_check(args):
    home = home_dir(args)
    d, meta = load_concept(home, args.concept)
    repos = load_repos(home)
    cache, bad, ok, counts = {}, [], 0, dict.fromkeys(TAGS, 0)
    files = [os.path.join(d, n) for n in ("notes.md", "lesson.md") if os.path.exists(os.path.join(d, n))]
    if not files:
        die(f"no notes.md or lesson.md in {d}")
    in_fence = False
    for path in files:
        text = open(path).read()
        for lineno, line in enumerate(text.splitlines(), 1):
            if line.lstrip().startswith("```"):
                in_fence = not in_fence
            if in_fence or line.lstrip().startswith("<!--"):
                continue
            for t in TAG_RX.findall(line):
                counts[t] += 1
            problems = check_line(line, repos, cache, args.max_range,
                                  require_tag=os.path.basename(path) == "notes.md")
            if not problems:
                ok += 1 if TAG_RX.search(line) else 0
            bad += [f"{os.path.basename(path)}:{lineno}: {p}" for p in problems]
        bad += [f"{os.path.basename(path)}: {p}" for p in check_quotes(text, repos, cache)]
    print(f"claims ok: {ok}, problems: {len(bad)}")
    print("evidence mix: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
    for b in bad:
        print("  " + b)
    sys.exit(1 if bad else 0)


# ---------------------------------------------------------------------------------------------
# expand: pull verbatim code into the lesson
# ---------------------------------------------------------------------------------------------

def cmd_expand(args):
    home = home_dir(args)
    d, meta = load_concept(home, args.concept)
    repos = load_repos(home)
    src_path = os.path.join(d, "lesson.src.md")
    if not os.path.exists(src_path):
        die(f"{src_path} does not exist")
    text, cache, errors = open(src_path).read(), {}, []

    def sub(m):
        ref = m.group(1)
        alias, path, a, b = parse_ref(ref)
        full = resolve(repos, alias, path)
        lines = read_lines(full, cache) if full else None
        if lines is None:
            errors.append(f"{ref}: file not found")
            return m.group(0)
        if a < 1 or b > len(lines) or a > b:
            errors.append(f"{ref}: out of range (file has {len(lines)} lines)")
            return m.group(0)
        if b - a + 1 > args.max_lines:
            errors.append(f"{ref}: {b - a + 1} lines is too long for a teaching excerpt (max {args.max_lines})")
            return m.group(0)
        lang = LANG.get(os.path.splitext(path)[1], "")
        code = "\n".join(normalize_block(lines[a - 1:b]))
        return f"<!-- quote {alias}:{path}:{a}-{b} -->\n```{lang}\n{code}\n```\n*{alias}:{path}:{a}-{b}*"

    out = EXCERPT_RX.sub(sub, text)
    if errors:
        for e in errors:
            print(f"  {e}", file=sys.stderr)
        die("nothing written; fix the placeholders above")
    with open(os.path.join(d, "lesson.md"), "w") as f:
        f.write(out)
    print(f"wrote lesson.md ({len(EXCERPT_RX.findall(text))} excerpts pulled from source)")


# ---------------------------------------------------------------------------------------------
# repos, search, deps
# ---------------------------------------------------------------------------------------------

def cmd_repo(args):
    home = home_dir(args)
    repos = load_repos(home)
    if args.action == "list":
        if not repos:
            print("no repos registered")
        for alias, r in sorted(repos.items()):
            print(f"{alias:20} {r.get('role', 'code'):9} {r['path']}")
        return
    if args.action == "add":
        if not args.alias or not args.path:
            die("usage: repo add ALIAS PATH [--role code|dep|upstream]")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", args.alias):
            die("alias may contain only letters, digits, hyphens and underscores")
        path = os.path.abspath(os.path.expanduser(args.path))
        if not os.path.isdir(path):
            die(f"{path} is not a directory")
        if path == home or path.startswith(home + os.sep) or home.startswith(path + os.sep):
            die("the notebook must live outside the repos it studies, and repos outside the notebook")
        repos[args.alias] = {"path": path, "role": args.role}
        save_json(os.path.join(home, "repos.json"), repos)
        print(f"registered {args.alias} -> {path} ({args.role})")
        return
    if args.action == "remove":
        if repos.pop(args.alias, None) is None:
            die(f"no repo {args.alias!r}")
        save_json(os.path.join(home, "repos.json"), repos)
        print(f"removed {args.alias}")


def walk(root, exts=None, include_deps=False):
    skip = SKIP_DIRS - ({"node_modules", "vendor"} if include_deps else set())
    for dp, dns, fns in os.walk(root):
        dns[:] = sorted(d for d in dns if d not in skip)
        for fn in sorted(fns):
            if exts is None or os.path.splitext(fn)[1] in exts:
                yield os.path.join(dp, fn)


def cmd_search(args):
    home = home_dir(args)
    repos = load_repos(home)
    if args.alias not in repos:
        die(f"unknown repo {args.alias!r}; registered: {', '.join(repos) or 'none'}")
    root = repos[args.alias]["path"]
    rx = re.compile("|".join(re.escape(t) for t in args.terms), re.I)
    hits = []
    for fp in walk(root, None if args.all_files else CODE_EXT, args.include_deps):
        try:
            with open(fp, errors="replace") as f:
                lines = f.read().splitlines()
        except OSError:
            continue
        found = [(i, l) for i, l in enumerate(lines, 1) if rx.search(l)]
        if found:
            hits.append((os.path.relpath(fp, root), found))
    hits.sort(key=lambda h: -len(h[1]))
    total = sum(len(h[1]) for h in hits)
    print(f"{total} hits in {len(hits)} files for {args.terms}")
    for rel, found in hits[:args.limit]:
        print(f"{len(found):4}  {rel}")
        for i, l in found[:args.per_file]:
            print(f"        {i}: {l.strip()[:110]}")
    if len(hits) > args.limit:
        print(f"... {len(hits) - args.limit} more files (raise --limit)")


def cmd_deps(args):
    """Declared and installed versions of dependencies, and where their source can be read."""
    home = home_dir(args)
    repos = load_repos(home)
    if args.alias not in repos:
        die(f"unknown repo {args.alias!r}")
    root = repos[args.alias]["path"]
    wanted = [w.lower() for w in args.match]
    shown = 0

    def want(name):
        return not wanted or any(w in name.lower() for w in wanted)

    pj = load_json(os.path.join(root, "package.json"), None)
    if pj:
        for sect in ("dependencies", "devDependencies", "peerDependencies"):
            for name, rng in sorted((pj.get(sect) or {}).items()):
                if not want(name):
                    continue
                inst = load_json(os.path.join(root, "node_modules", name, "package.json"), None)
                where = f"node_modules/{name}" if inst else "not installed (run the package manager)"
                ver = inst.get("version") if inst else "?"
                print(f"npm  {name:32} declared {rng:14} installed {ver:10} {where}")
                shown += 1
    gm = os.path.join(root, "go.mod")
    if os.path.exists(gm):
        cache = None
        try:
            cache = subprocess.run(["go", "env", "GOMODCACHE"], capture_output=True, text=True,
                                   timeout=10, cwd=root).stdout.strip() or None
        except (OSError, subprocess.SubprocessError):
            pass
        vendored = os.path.isdir(os.path.join(root, "vendor"))
        for line in open(gm):
            m = re.match(r"\s*(?:require\s+)?([\w.\-/]+\.[\w.\-/]+)\s+(v[\w.\-+]+)", line)
            if not m or not want(m.group(1)):
                continue
            mod, ver = m.groups()
            if vendored:
                where = f"vendor/{mod}"
            elif cache:
                where = f"{cache}/{mod}@{ver}" + ("" if os.path.isdir(f"{cache}/{mod}@{ver}")
                                                    else "  (missing: go mod download)")
            else:
                where = "module cache (go not available to locate it)"
            print(f"go   {mod:32} version {ver:20} {where}")
            shown += 1
    if not shown:
        print("no matching dependencies found (looked at package.json and go.mod)")


# ---------------------------------------------------------------------------------------------
# fingerprint: find data structures by shape, not by name
# ---------------------------------------------------------------------------------------------

def _rx(p, flags=0):
    return re.compile(p, flags)


# Each fingerprint: required patterns (all must match in a file) and optional markers that say
# which refinements are present. These are heuristics; a hit is a lead for the researcher.
FINGERPRINTS = {
    "union-find": {
        "required": [_rx(r"\b(parents?|roots?|uf|dsu)\b\s*(\[|\.)"), _rx(r"\b(find|findRoot|find_root|getRoot)\s*\(")],
        "markers": {
            "path compression": _rx(r"\b(parents?|roots?)\s*\[\s*\w+\s*\]\s*=\s*(this\.|self\.)?(find|findRoot|find_root)\w*\("),
            "union by rank/size": _rx(r"\b(rank|sz|size)\s*\[\s*\w+\s*\]\s*[<>+]"),
        },
    },
    "lru-cache": {
        "required": [_rx(r"\b(lru|evict\w*)\b", re.I),
                     _rx(r"MoveToFront|moveToFront|move_to_front|moveToHead|\.keys\(\)\.next\(\)|\.delete\(")],
        "markers": {"hash map + linked list": _rx(r"container/list|\.prev\b.*\.next\b|\bprev\b.*\bnext\b"),
                    "Map insertion-order trick": _rx(r"\.keys\(\)\.next\(\)")},
    },
    "ring-buffer": {
        "required": [_rx(r"\b(head|tail|readIdx|writeIdx|read_idx|write_idx|readPos|writePos)\b"),
                     _rx(r"%\s*(\w*cap\w*|\w*size\w*|\w*len\w*|N)\b|&\s*\(\s*\w+\s*-\s*1\s*\)|&\s*\w*mask\w*", re.I)],
        "markers": {"power-of-two mask": _rx(r"&\s*\(\s*\w+\s*-\s*1\s*\)|&\s*\w*mask", re.I)},
    },
    "trie": {
        "required": [_rx(r"\b(children|child)\b\s*(\[|\.|:|=)"),
                     _rx(r"\b(isEnd|is_end|isWord|is_word|terminal|isTerminal|endOfWord|end_of_word)\b")],
        "markers": {},
    },
    "heap / priority queue": {
        "required": [_rx(r"siftUp|siftDown|sift_up|sift_down|bubbleUp|bubbleDown|heapify|percolate|heap\.(Init|Push|Pop)|container/heap")],
        "markers": {"Go container/heap": _rx(r"container/heap")},
    },
    "bloom filter": {
        "required": [_rx(r"bloom", re.I), _rx(r"murmur|fnv|xxhash|hash", re.I)],
        "markers": {},
    },
    "graph traversal (BFS/DFS)": {
        "required": [_rx(r"\b(visited|seen)\b"), _rx(r"\b(queue|stack|frontier|neighbors|neighbours|adjacency|adj)\b", re.I)],
        "markers": {"queue-based (BFS)": _rx(r"\bqueue\b.*(shift|pop|dequeue)|(shift|dequeue)\(\)", re.I),
                    "recursive (DFS)": _rx(r"\bdfs\b|\bvisit\w*\(", re.I)},
    },
    "topological sort": {
        "required": [_rx(r"in_?degree|topolog", re.I)],
        "markers": {},
    },
    "shortest path": {
        "required": [_rx(r"\b(dist|distance|dists)\s*(\[|\.get)"), _rx(r"heap|priority|\bpq\b", re.I)],
        "markers": {},
    },
}


def fingerprint_file(text):
    """[(structure, strong_markers, first_line)] for the shapes that match this file's text."""
    out = []
    for name, fp in FINGERPRINTS.items():
        if not all(r.search(text) for r in fp["required"]):
            continue
        m = fp["required"][0].search(text)
        line = text.count("\n", 0, m.start()) + 1
        marks = [label for label, r in fp["markers"].items() if r.search(text)]
        out.append((name, marks, line))
    return out


def cmd_fingerprint(args):
    home = home_dir(args)
    repos = load_repos(home)
    if args.alias not in repos:
        die(f"unknown repo {args.alias!r}")
    root = repos[args.alias]["path"]
    wanted = [k.lower() for k in args.kind]
    found = {}
    for fp in walk(root, CODE_EXT, args.include_deps):
        try:
            if os.path.getsize(fp) > args.max_bytes:
                continue
            with open(fp, errors="replace") as f:
                text = f.read()
        except OSError:
            continue
        for name, marks, line in fingerprint_file(text):
            if wanted and not any(w in name.lower() for w in wanted):
                continue
            found.setdefault(name, []).append((os.path.relpath(fp, root), line, marks))
    if not found:
        print("no known data-structure shapes found")
        return
    print("Shape matches are leads, not conclusions: a researcher must read the code and confirm.")
    for name in sorted(found):
        rows = found[name]
        print(f"\n{name}  ({len(rows)} files)")
        for rel, line, marks in sorted(rows, key=lambda r: (-len(r[2]), r[0]))[:args.limit]:
            extra = f"  [{', '.join(marks)}]" if marks else ""
            print(f"    {rel}:{line}{extra}")


# ---------------------------------------------------------------------------------------------
# concepts: create, mark, status, stale
# ---------------------------------------------------------------------------------------------

def cmd_concept(args):
    home = home_dir(args)
    if args.action != "new":
        die("usage: concept new SLUG --kind K --repo ALIAS[,ALIAS] [--title T]")
    d = concept_dir(home, args.slug)
    if os.path.exists(os.path.join(d, "meta.json")):
        die(f"concept {args.slug!r} already exists; refusing to overwrite it")
    repos = load_repos(home)
    aliases = [a for a in (args.repo or "").split(",") if a]
    for a in aliases:
        if a not in repos:
            die(f"unknown repo {a!r}; register it first with: dl.py repo add")
    save_json(os.path.join(d, "meta.json"), {
        "id": args.slug, "title": args.title or args.slug.replace("-", " "), "kind": args.kind,
        "repos": aliases, "status": "new", "created": now(), "updated": now(), "files": {}})
    print(f"created {d}")


def cited_files(text, repos):
    out = set()
    for m in CITE_RX.finditer(text):
        if m.group(1) in repos and resolve(repos, m.group(1), m.group(2)):
            out.add((m.group(1), m.group(2)))
    return sorted(out)


def git_head(path):
    try:
        r = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=path, capture_output=True,
                           text=True, timeout=10)
        return r.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def cmd_mark(args):
    home = home_dir(args)
    d, meta = load_concept(home, args.concept)
    repos = load_repos(home)
    notes = os.path.join(d, "notes.md")
    if args.status in ("researched", "verified", "taught"):
        if not os.path.exists(notes):
            die("notes.md does not exist yet; nothing to record")
        files = {}
        for alias, path in cited_files(open(notes).read(), repos):
            full = resolve(repos, alias, path)
            if full and os.path.isfile(full):
                files[f"{alias}:{path}"] = sha1(full)
        meta["files"] = files
        meta["heads"] = {a: h for a in meta.get("repos", []) if a in repos
                         and (h := git_head(repos[a]["path"]))}
        if not files:
            print("warning: notes cite no registered code; staleness cannot be tracked")
    meta["status"] = args.status
    meta["updated"] = now()
    save_json(os.path.join(d, "meta.json"), meta)
    print(f"{args.concept} -> {args.status} ({len(meta.get('files', {}))} files tracked)")


def concept_stale(meta, repos):
    out = []
    for key, old in sorted(meta.get("files", {}).items()):
        alias, path = key.split(":", 1)
        full = resolve(repos, alias, path)
        if full is None or not os.path.isfile(full):
            out.append((key, "removed or moved"))
        elif sha1(full) != old:
            out.append((key, "changed"))
    return out


def cmd_stale(args):
    home = home_dir(args)
    repos = load_repos(home)
    base = os.path.join(home, "concepts")
    slugs = [args.concept] if args.concept else (sorted(os.listdir(base)) if os.path.isdir(base) else [])
    any_stale = False
    for slug in slugs:
        d, meta = load_concept(home, slug)
        if meta["status"] not in ("verified", "taught"):
            continue
        rows = concept_stale(meta, repos)
        if rows:
            any_stale = True
            print(f"STALE {slug} ({meta['title']}): {len(rows)} cited file(s) changed since you learned it")
            for key, why in rows:
                print(f"    {why}: {key}")
    if not any_stale:
        print("nothing you have learned has changed underneath you")
    sys.exit(1 if any_stale else 0)


def cmd_status(args):
    home = home_dir(args)
    base = os.path.join(home, "concepts")
    repos = load_repos(home)
    if not os.path.isdir(base) or not os.listdir(base):
        print("no concepts yet")
        return
    for slug in sorted(os.listdir(base)):
        meta = load_json(os.path.join(base, slug, "meta.json"))
        if not meta:
            continue
        stale = len(concept_stale(meta, repos)) if meta["status"] in ("verified", "taught") else 0
        flag = f"  STALE({stale})" if stale else ""
        print(f"{slug:28} {meta['kind']:10} {meta['status']:10} {','.join(meta.get('repos', []))}{flag}")


# ---------------------------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(prog="dl.py", description="design-lens mechanical helpers")
    ap.add_argument("--home", help="notebook directory (default $DL_HOME or ~/system-design-notebook)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("repo", help="register the code, dependency source or upstream source you study")
    p.add_argument("action", choices=["add", "list", "remove"])
    p.add_argument("alias", nargs="?")
    p.add_argument("path", nargs="?")
    p.add_argument("--role", choices=ROLES, default="code")
    p.set_defaults(fn=cmd_repo)

    p = sub.add_parser("search", help="find where terms occur in a registered repo")
    p.add_argument("alias")
    p.add_argument("terms", nargs="+")
    p.add_argument("--limit", type=int, default=15)
    p.add_argument("--per-file", type=int, default=3)
    p.add_argument("--include-deps", action="store_true", help="also search node_modules and vendor")
    p.add_argument("--all-files", action="store_true", help="not only source files")
    p.set_defaults(fn=cmd_search)

    p = sub.add_parser("deps", help="installed versions of dependencies and where their source is")
    p.add_argument("alias")
    p.add_argument("match", nargs="*", help="only dependencies whose name contains one of these")
    p.set_defaults(fn=cmd_deps)

    p = sub.add_parser("fingerprint", help="find data structures and algorithms by their shape")
    p.add_argument("alias")
    p.add_argument("kind", nargs="*", help="limit to shapes whose name contains one of these")
    p.add_argument("--limit", type=int, default=8)
    p.add_argument("--include-deps", action="store_true")
    p.add_argument("--max-bytes", type=int, default=400_000)
    p.set_defaults(fn=cmd_fingerprint)

    p = sub.add_parser("concept", help="create a concept to study")
    p.add_argument("action", choices=["new"])
    p.add_argument("slug")
    p.add_argument("--kind", choices=KINDS, required=True)
    p.add_argument("--repo", help="comma-separated aliases")
    p.add_argument("--title")
    p.set_defaults(fn=cmd_concept)

    p = sub.add_parser("check", help="verify notes.md and lesson.md against the real code")
    p.add_argument("concept")
    p.add_argument("--max-range", type=int, default=80, help="widest cited range, in lines")
    p.set_defaults(fn=cmd_check)

    p = sub.add_parser("expand", help="turn lesson.src.md into lesson.md with real code pulled in")
    p.add_argument("concept")
    p.add_argument("--max-lines", type=int, default=40)
    p.set_defaults(fn=cmd_expand)

    p = sub.add_parser("mark", help="set a concept's status; records hashes of the code it cites")
    p.add_argument("concept")
    p.add_argument("--status", choices=STATUSES, required=True)
    p.set_defaults(fn=cmd_mark)

    p = sub.add_parser("stale", help="learned concepts whose cited code has since changed")
    p.add_argument("concept", nargs="?")
    p.set_defaults(fn=cmd_stale)

    sub.add_parser("status", help="list concepts").set_defaults(fn=cmd_status)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
