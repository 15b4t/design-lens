"""Tests for scripts/dl.py. Run: python3 -m unittest discover -s tests -v"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

DL = os.path.join(os.path.dirname(__file__), "..", "scripts", "dl.py")

QUEUE_TS = """\
export class Worker {
  constructor(private queue: Queue) {}

  async run(job: Job) {
    try {
      await this.handle(job);
      await this.queue.ack(job.id);
    } catch (err) {
      await this.queue.retryLater(job.id);
    }
  }
}
"""

# Padding so that a symbol sitting a few lines away from a cited range is genuinely outside it.
PADDED_TS = "\n".join(["// filler"] * 6 + ["function nearby() {}"] + ["// filler"] * 12
                      + ["function target() { return 1 }"] + ["// filler"] * 4) + "\n"


class Env(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = os.path.join(self.tmp.name, "notebook")
        self.repo = os.path.join(self.tmp.name, "work-repo")
        os.makedirs(os.path.join(self.repo, "src"))
        self.write("src/worker.ts", QUEUE_TS)
        self.write("src/padded.ts", PADDED_TS)
        self.dl("repo", "add", "api", self.repo)
        self.dl("concept", "new", "queues", "--kind", "mechanism", "--repo", "api")

    def write(self, rel, text):
        path = os.path.join(self.repo, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)

    def cfile(self, name, text):
        path = os.path.join(self.home, "concepts", "queues", name)
        with open(path, "w") as f:
            f.write(text)
        return path

    def dl(self, *args, ok=True):
        r = subprocess.run([sys.executable, DL, "--home", self.home, *args], capture_output=True, text=True)
        if ok:
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r

    def check(self, notes, **kw):
        self.cfile("notes.md", notes)
        return self.dl("check", "queues", ok=False, **kw)


class CheckClaims(Env):
    def test_valid_code_claim_passes(self):
        r = self.check("- [code] The worker acks only after success (`Worker.run` api:src/worker.ts:4-11)\n")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("claims ok: 1", r.stdout)

    def test_claim_without_symbol_fails(self):
        r = self.check("- [code] The worker acks after success (api:src/worker.ts:4-11)\n")
        self.assertEqual(r.returncode, 1)
        self.assertIn("names no symbol", r.stdout)

    def test_symbol_outside_exact_range_fails_even_if_nearby(self):
        # `nearby` is on line 7; the cited range is 20-20 (`target`). A padded window would pass it.
        r = self.check("- [code] It does a thing (`nearby` api:src/padded.ts:20-20)\n")
        self.assertEqual(r.returncode, 1)
        self.assertIn("not found inside the cited range", r.stdout)

    def test_symbol_inside_range_passes(self):
        r = self.check("- [code] It returns one (`target` api:src/padded.ts:20-20)\n")
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_wide_range_rejected(self):
        self.write("src/big.ts", "\n".join(f"const v{i} = {i}" for i in range(300)) + "\n")
        r = self.check("- [code] It defines values (`v3` api:src/big.ts:1-250)\n")
        self.assertEqual(r.returncode, 1)
        self.assertIn("proves nothing", r.stdout)

    def test_untagged_citation_fails(self):
        r = self.check("- The worker acks (`Worker` api:src/worker.ts:1-3)\n")
        self.assertEqual(r.returncode, 1)
        self.assertIn("no evidence tag", r.stdout)

    def test_theory_line_citing_code_fails(self):
        r = self.check("- [theory] Acks should come last (`Worker` api:src/worker.ts:1-3)\n")
        self.assertEqual(r.returncode, 1)
        self.assertIn("[theory] line cites code", r.stdout)

    def test_theory_without_citation_passes(self):
        r = self.check("- [theory] At-least-once delivery means consumers must be idempotent.\n")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("theory 1", r.stdout)

    def test_role_mismatch_fails(self):
        r = self.check("- [dep] It acks (`Worker` api:src/worker.ts:1-3)\n")
        self.assertEqual(r.returncode, 1)
        self.assertIn("registered as role 'code'", r.stdout)

    def test_two_tags_on_one_line_fails(self):
        r = self.check("- [code] [theory] both at once (`Worker` api:src/worker.ts:1-3)\n")
        self.assertEqual(r.returncode, 1)
        self.assertIn("more than one evidence tag", r.stdout)

    def test_out_of_range_and_missing_file_fail(self):
        r = self.check("- [code] gone (`Worker` api:src/worker.ts:90-95)\n"
                       "- [code] missing (`Worker` api:src/nope.ts:1-3)\n")
        self.assertEqual(r.returncode, 1)
        self.assertIn("out of range", r.stdout)
        self.assertIn("does not exist", r.stdout)

    def test_path_escape_rejected(self):
        r = self.check("- [code] escape (`Worker` api:../secret.ts:1-3)\n")
        self.assertEqual(r.returncode, 1)

    def test_unknown_alias_on_tagged_claim_fails(self):
        r = self.check("- [code] elsewhere (`Worker` web:src/worker.ts:1-3)\n")
        self.assertEqual(r.returncode, 1)
        self.assertIn("unknown repo alias", r.stdout)

    def test_dependency_role_claim_passes(self):
        dep = os.path.join(self.tmp.name, "lib")
        os.makedirs(dep)
        with open(os.path.join(dep, "q.js"), "w") as f:
            f.write("function deliver() {\n  return 1\n}\n")
        self.dl("repo", "add", "queuelib", dep, "--role", "dep")
        r = self.check("- [dep] delivery happens here (`deliver` queuelib:q.js:1-3)\n")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("dep 1", r.stdout)


class ExpandAndQuotes(Env):
    SRC = "## Ack timing\n\n{{excerpt api:src/worker.ts:4-11}}\n\nThe ack comes after the handler.\n"

    def test_expand_pulls_verbatim_code_and_check_passes(self):
        self.cfile("lesson.src.md", self.SRC)
        self.dl("expand", "queues")
        with open(os.path.join(self.home, "concepts", "queues", "lesson.md")) as f:
            lesson = f.read()
        self.assertIn("<!-- quote api:src/worker.ts:4-11 -->", lesson)
        self.assertIn("await this.queue.ack(job.id);", lesson)
        self.assertEqual(self.dl("check", "queues", ok=False).returncode, 0)

    def test_check_flags_quote_after_code_changes(self):
        self.cfile("lesson.src.md", self.SRC)
        self.dl("expand", "queues")
        self.write("src/worker.ts", QUEUE_TS.replace("ack(job.id)", "ack(job.id, true)"))
        r = self.dl("check", "queues", ok=False)
        self.assertEqual(r.returncode, 1)
        self.assertIn("quote does not match", r.stdout)

    def test_check_flags_retyped_quote(self):
        self.cfile("lesson.md", "<!-- quote api:src/worker.ts:4-11 -->\n```ts\nasync run(job) {\n  ack()\n}\n```\n")
        r = self.dl("check", "queues", ok=False)
        self.assertEqual(r.returncode, 1)
        self.assertIn("quote does not match", r.stdout)

    def test_expand_writes_nothing_on_bad_placeholder(self):
        self.cfile("lesson.src.md", "{{excerpt api:src/worker.ts:4-11}}\n{{excerpt api:src/worker.ts:80-90}}\n")
        r = self.dl("expand", "queues", ok=False)
        self.assertEqual(r.returncode, 2)
        self.assertFalse(os.path.exists(os.path.join(self.home, "concepts", "queues", "lesson.md")))

    def test_expand_rejects_overlong_excerpt(self):
        self.cfile("lesson.src.md", "{{excerpt api:src/worker.ts:1-12}}\n")
        r = self.dl("expand", "queues", "--max-lines", "5", ok=False)
        self.assertEqual(r.returncode, 2)
        self.assertIn("too long", r.stderr)


class LessonRules(Env):
    def test_lesson_prose_may_cite_without_a_tag_but_notes_may_not(self):
        self.cfile("lesson.md", "The ack lives in `Worker.run` (api:src/worker.ts:4-11).\n")
        self.assertEqual(self.dl("check", "queues", ok=False).returncode, 0)
        os.remove(os.path.join(self.home, "concepts", "queues", "lesson.md"))
        self.assertEqual(self.check("The ack lives in `Worker.run` (api:src/worker.ts:4-11).\n").returncode, 1)

    def test_untagged_lesson_citation_is_still_verified(self):
        self.cfile("lesson.md", "The ack is in `Worker.nothing` (api:src/worker.ts:4-11).\n")
        r = self.dl("check", "queues", ok=False)
        self.assertEqual(r.returncode, 1)
        self.assertIn("not found inside the cited range", r.stdout)
        self.cfile("lesson.md", "It lives in the old file (`Worker` api:src/gone.ts:1-3).\n")
        self.assertIn("does not exist", self.dl("check", "queues", ok=False).stdout)

    def test_expanded_caption_is_exempt(self):
        self.cfile("lesson.md", "*api:src/worker.ts:4-11*\n")
        self.assertEqual(self.dl("check", "queues", ok=False).returncode, 0)

    def test_tagged_claim_in_lesson_is_still_verified(self):
        self.cfile("lesson.md", "- [code] It acks (`Worker` api:src/worker.ts:4-11)\n")
        r = self.dl("check", "queues", ok=False)
        self.assertEqual(r.returncode, 1)
        self.assertIn("not found inside the cited range", r.stdout)


class Staleness(Env):
    def learn(self):
        self.cfile("notes.md", "- [code] acks after success (`Worker.run` api:src/worker.ts:4-11)\n")
        self.dl("mark", "queues", "--status", "verified")

    def test_unchanged_is_not_stale(self):
        self.learn()
        r = self.dl("stale", "queues", ok=False)
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_changed_file_is_stale(self):
        self.learn()
        self.write("src/worker.ts", QUEUE_TS + "// edit\n")
        r = self.dl("stale", "queues", ok=False)
        self.assertEqual(r.returncode, 1)
        self.assertIn("changed: api:src/worker.ts", r.stdout)

    def test_removed_file_is_stale(self):
        self.learn()
        os.remove(os.path.join(self.repo, "src", "worker.ts"))
        r = self.dl("stale", "queues", ok=False)
        self.assertEqual(r.returncode, 1)
        self.assertIn("removed or moved", r.stdout)

    def test_unverified_concept_is_ignored(self):
        self.cfile("notes.md", "- [code] x (`Worker` api:src/worker.ts:1-3)\n")
        self.dl("mark", "queues", "--status", "briefed")
        self.write("src/worker.ts", "changed\n")
        self.assertEqual(self.dl("stale", "queues", ok=False).returncode, 0)


class Fingerprints(Env):
    def test_union_find_with_path_compression_found_without_its_name(self):
        self.write("src/groups.js", "const parent = [];\nfunction find(x) {\n  if (parent[x] !== x) parent[x] = find(parent[x]);\n"
                   "  return parent[x];\n}\nfunction union(a, b) { parent[find(a)] = find(b); }\n")
        out = self.dl("fingerprint", "api").stdout
        self.assertIn("union-find", out)
        self.assertIn("path compression", out)
        self.assertIn("src/groups.js", out)

    def test_union_find_without_compression_is_reported_without_the_marker(self):
        self.write("src/naive.js", "const parent = [];\nfunction find(x) {\n  while (parent[x] !== x) x = parent[x];\n  return x;\n}\n")
        out = self.dl("fingerprint", "api", "union").stdout
        self.assertIn("src/naive.js", out)
        self.assertNotIn("path compression", out)

    def test_go_lru(self):
        self.write("cache/lru.go", 'import "container/list"\ntype LRU struct{ ll *list.List }\n'
                   "func (c *LRU) Get(k string) { c.ll.MoveToFront(e) }\nfunc (c *LRU) evict() {}\n")
        out = self.dl("fingerprint", "api", "lru").stdout
        self.assertIn("cache/lru.go", out)

    def test_ring_buffer_with_mask(self):
        self.write("src/ring.c", "buf[head & (cap - 1)] = v;\nhead++;\nint n = tail;\n")
        out = self.dl("fingerprint", "api", "ring").stdout
        self.assertIn("power-of-two mask", out)

    def test_c_free_list_allocator(self):
        self.write("src/malloc.c", "block_t *head = NULL;\nblock_t *find_free_block(size_t n) {\n"
                   "  block_t *curr = head;\n  while (curr) { if (curr->size >= n) return curr; curr = curr->next; }\n"
                   "  return NULL;\n}\nvoid ifree(void *p) { /* coalesce consecutive free blocks */ }\n")
        out = self.dl("fingerprint", "api", "linked").stdout
        self.assertIn("src/malloc.c", out)
        self.assertIn("allocator free list", out)

    def test_test_files_skipped_unless_asked(self):
        self.write("test/lru.test.ts", "class LRU { evict() { this.map.delete(k) } }\n")
        self.write("cache/lru_test.go", "func TestLRU() { c.evict(); l.MoveToFront(e) }\n")
        out = self.dl("fingerprint", "api").stdout
        self.assertIn("no known data-structure shapes", out)
        self.assertIn("2 test files skipped", out)
        self.assertIn("lru-cache", self.dl("fingerprint", "api", "--tests").stdout)

    def test_plain_code_matches_nothing(self):
        out = self.dl("fingerprint", "api").stdout
        self.assertIn("no known data-structure shapes", out)

    def test_dependency_dirs_skipped_unless_asked(self):
        self.write("node_modules/x/trie.js", "const children = {};\nlet isEnd = false;\n")
        self.assertIn("no known", self.dl("fingerprint", "api").stdout)
        self.assertIn("trie", self.dl("fingerprint", "api", "--include-deps").stdout)


class SearchAndDeps(Env):
    def test_search_groups_hits_by_file(self):
        out = self.dl("search", "api", "retryLater", "ack").stdout
        self.assertIn("src/worker.ts", out)
        self.assertIn("hits in 1 files", out)

    def test_search_skips_node_modules(self):
        self.write("node_modules/q/index.js", "ack ack ack\n")
        self.assertNotIn("node_modules", self.dl("search", "api", "ack").stdout)
        self.assertIn("node_modules", self.dl("search", "api", "ack", "--include-deps").stdout)

    def test_deps_reports_installed_version(self):
        self.write("package.json", json.dumps({"dependencies": {"bullmq": "^5.0.0", "left-pad": "1.0.0"}}))
        self.write("node_modules/bullmq/package.json", json.dumps({"version": "5.1.2"}))
        out = self.dl("deps", "api", "bullmq").stdout
        self.assertIn("installed 5.1.2", out)
        self.assertNotIn("left-pad", out)

    def test_deps_flags_not_installed(self):
        self.write("package.json", json.dumps({"dependencies": {"ioredis": "^5"}}))
        self.assertIn("not installed", self.dl("deps", "api").stdout)

    def test_deps_reads_go_mod(self):
        self.write("go.mod", "module x\n\nrequire (\n\tgithub.com/redis/go-redis/v9 v9.5.1\n)\n")
        self.write("vendor/github.com/redis/go-redis/v9/doc.go", "package redis\n")
        out = self.dl("deps", "api", "redis").stdout
        self.assertIn("v9.5.1", out)
        self.assertIn("vendor/github.com/redis/go-redis/v9", out)


class State(Env):
    def test_notebook_inside_repo_refused(self):
        inside = os.path.join(self.repo, "notebook")
        r = subprocess.run([sys.executable, DL, "--home", inside, "repo", "add", "x", self.repo],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)
        self.assertIn("outside", r.stderr)

    def test_corrupt_repos_json_is_not_overwritten(self):
        path = os.path.join(self.home, "repos.json")
        with open(path, "w") as f:
            f.write("{not json")
        r = self.dl("repo", "add", "web", self.repo, ok=False)
        self.assertEqual(r.returncode, 2)
        with open(path) as f:
            self.assertEqual(f.read(), "{not json")

    def test_concept_new_refuses_to_overwrite(self):
        r = self.dl("concept", "new", "queues", "--kind", "mechanism", "--repo", "api", ok=False)
        self.assertEqual(r.returncode, 2)
        self.assertIn("already exists", r.stderr)

    def test_concept_id_must_be_kebab_case(self):
        r = self.dl("concept", "new", "../evil", "--kind", "mechanism", ok=False)
        self.assertEqual(r.returncode, 2)

    def test_status_lists_concepts(self):
        self.assertIn("queues", self.dl("status").stdout)


if __name__ == "__main__":
    unittest.main()
