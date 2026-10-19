#!/bin/bash
# parallel-crossover.sh — at what wave width does fanning out actually save time?
#
# The fast mode trades money for wall time: one subagent per task of a wave, all
# dispatched in one message, so the developer waits for the longest task instead
# of the sum. Below some width the agents' own start-up and the driver's
# bookkeeping eat the saving. `parallel.min_wave` is that width, and a number
# chosen by feel is folklore (CLAUDE.md rule 1). This measures it.
#
#   bash scripts/probes/parallel-crossover.sh                 # N = 2 4 8 12, both arms
#   bash scripts/probes/parallel-crossover.sh 4 8             # only those widths
#   ARMS=fast bash scripts/probes/parallel-crossover.sh 12    # one arm
#   DRIVER=opus KEEP=1 bash scripts/probes/parallel-crossover.sh 2
#   WORKLOAD=turns bash scripts/probes/parallel-crossover.sh 2 3 4 6 8
#
# Two workloads. WORKLOAD=spec (the default) is described just below.
# WORKLOAD=turns is the case the fast mode exists for: work bound by turns, not
# by tokens. Each item is a ~240-line module nobody has seen, whose conventions
# (which normaliser, which rounding) live only in the module; a stub whose spec
# leaves out two behaviours; and a slow test (TEST_SLEEP seconds in setUpClass,
# default 10) whose cases are sealed, so reading it reveals nothing, and
# which stops at the first failing case with a message naming the missing
# behaviour. An item cannot be finished without a read, a write and at least two
# red runs before the green one — and the spec workload showed that a main
# session batches anything it can finish without looking.
#
# Costs real money: a few dollars for the full grid. Each session is bounded by
# --max-budget-usd. Writes nothing outside its own temporary directories.
#
# For each N, the same throwaway project — N stub modules in N files, each of two
# to four functions with a written spec in its docstrings and its own unittest of
# eight to twelve cases — is given to two sessions:
#
#   economy  the driver implements every item itself, no subagents.
#   fast     the driver starts one efficiency:implementer-fast per item, all N in
#            one assistant message, and runs the gate once they are back.
#
# The items are deliberately not one-liners — an expression evaluator, an INI
# parser, a CSV reader and writer, an LRU cache, Dijkstra, canonical Roman
# numerals both ways, semver... — each about a minute of real work. A first cut
# with one-function items took Sonnet ~5 s apiece, and at that size the measured
# crossover would only be agent start-up.
#
# Read per session: elapsed seconds, outside the process, on the uptime clock
# — on a laptop that dozes, a 10 s sleep took 15 to 23 s of wall time on
# 2026-10-19 while the monotonic clock said 10.0 — the driver's
# reported total_cost_usd (the LAST result event: under -p a fast session emits one
# per finished subagent, each cumulative), the spend hooks/lib/spend.py computes
# from the main transcript plus subagents/agent-*.jsonl (on 2026-10-18 that
# figure ran 2-4x high: it sums every content-block row of a message, each
# carrying the whole message's usage), items green afterwards, how many
# delegations left in the largest single message, and — from the subagent
# transcripts' first and last timestamps — how many subagents were ever running
# at once, which is where a concurrency cap would show.
#
# The sessions run with `--setting-sources project,local`, like every probe here.

set -uo pipefail

cd "$(dirname "$0")/../.." || exit 2
PLUGIN=$(pwd)

command -v claude  >/dev/null 2>&1 || { echo "claude not on PATH" >&2; exit 2; }
command -v python3 >/dev/null 2>&1 || { echo "python3 not on PATH" >&2; exit 2; }

DRIVER=${DRIVER:-sonnet}
BUDGET=${BUDGET:-3.00}
ARMS=${ARMS:-economy fast}
WORKLOAD=${WORKLOAD:-spec}
WIDTHS=${*:-2 4 8 12}
PROJECTS_DIR=${CLAUDE_CONFIG_DIR:-$HOME/.claude}/projects
GATE_CMD="python3 -m unittest discover -s tests -q"

case "$WORKLOAD" in spec|turns) ;; *) echo "WORKLOAD is spec or turns, got '$WORKLOAD'" >&2; exit 2 ;; esac
for n in $WIDTHS; do
    case "$n" in 1|2|3|4|5|6|7|8|9|10|11|12) ;; *) echo "widths are 1..12, got '$n'" >&2; exit 2 ;; esac
done

echo "claude: $(claude --version 2>/dev/null | head -1)"
echo "driver: $DRIVER   budget ceiling per session: \$$BUDGET   widths: $WIDTHS   arms: $ARMS   workload: $WORKLOAD"
echo

DIRS=()
# shellcheck disable=SC2329  # invoked by the trap below
cleanup() {
    if [ -n "${KEEP:-}" ]; then echo "kept: ${DIRS[*]:-}"; return; fi
    for d in "${DIRS[@]:-}"; do [ -n "$d" ] && rm -rf "$d"; done
}
trap cleanup EXIT

# ── the project: the first N items of a fixed pool of twelve modules ─────────
scaffold_turns() {
    local dir="$1" n="$2"
    python3 - "$dir" "$n" <<'PY' || return 1
import base64, hashlib, json, os, random, sys, zlib
from decimal import Decimal, ROUND_HALF_EVEN
d, n = sys.argv[1], int(sys.argv[2])
SLEEP = int(os.environ.get("TEST_SLEEP", "10"))
# Turn-bound items. Each is a ~300-line module nobody has seen, whose
# conventions (which normaliser, which rounding) are only in the module itself;
# a stub whose spec leaves out two behaviours; and a slow test that reveals
# those behaviours one at a time, through its failure message. Reading the test
# does not help: each case keeps only a digest of its expected output, and its
# message is sealed with the previous case's expected output. Plain base64 was
# not enough — a Sonnet session read the cases straight out of it — and nor was
# compression: the next one decompressed them with a one-line script. So each item needs a read, a write, and
# at least two red runs before a green one — turns, not tokens.
NAMES = ["billing", "payroll", "freight", "grants", "rentals", "tuition", "customs", "royalties",
         "pensions", "tolls", "licences", "subsidies"]
RULES = [
    ("deprecated", "records whose code is flagged deprecated in CODES are skipped"),
    ("comma", "amounts may use ',' as a thousands separator"),
    ("refund", "a record with refund=True subtracts its contribution instead of adding it"),
    ("zero", "categories whose total is exactly zero are left out of the result"),
    ("empty", "an empty amount string counts as zero"),
    ("suffix", "a code may carry a '/REGION' suffix (e.g. 'ab-12/EU'), which is ignored"),
]
CATS = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel"]


def xor(data, key):
    stream = b""
    while len(stream) < len(data):
        stream += hashlib.sha256((key + str(len(stream))).encode()).digest()
    return bytes(x ^ y for x, y in zip(data, stream))


def norm(c):
    return c.strip().upper().replace("-", "").replace(" ", "")


def cents(x):
    return x.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)


def reference(records, codes, rules):
    totals = {}
    for r in records:
        code = r["code"]
        if "suffix" in rules:
            code = code.split("/")[0]
        cat, rate, dep = codes[norm(code)]
        if "deprecated" in rules and dep:
            continue
        amt = r["amount"]
        if "comma" in rules:
            amt = amt.replace(",", "")
        if "empty" in rules and amt == "":
            amt = "0"
        v = cents(Decimal(amt) * rate / 10000)
        if "refund" in rules and r.get("refund"):
            v = -v
        totals[cat] = totals.get(cat, Decimal("0.00")) + v
    if "zero" in rules:
        totals = {k: v for k, v in totals.items() if v != 0}
    return {k: str(v) for k, v in totals.items()}


os.makedirs(os.path.join(d, "src")); os.makedirs(os.path.join(d, "tests"))
open(os.path.join(d, "src", "__init__.py"), "w").close()
names = []
for k in range(n):
    rnd = random.Random(1000 + k)
    mod = NAMES[k]
    names.append(mod)
    a, b = RULES[k % 6], RULES[(k + 2) % 6]
    codes = {}
    while len(codes) < 180:
        c = "%s%s%02d" % (rnd.choice("ABCDEFGHJK"), rnd.choice("LMNPQRSTUV"), rnd.randrange(100))
        codes[c] = (rnd.choice(CATS), rnd.randrange(50, 2500), rnd.random() < 0.12)
    live = [c for c, v in codes.items() if not v[2]]
    dead = [c for c, v in codes.items() if v[2]]

    def dash(c):
        return c[:2].lower() + "-" + c[2:]

    base = [{"code": dash(rnd.choice(live)) if i % 2 else rnd.choice(live),
             "amount": "%d.%02d" % (rnd.randrange(1, 900), rnd.randrange(100))} for i in range(8)]
    used_cats = {codes[norm(r["code"])][0] for r in base}
    features = {
        "deprecated": [{"code": rnd.choice(dead), "amount": "120.00"}],
        "comma": [{"code": rnd.choice(live), "amount": "1,250.50"}],
        "refund": [{"code": base[0]["code"], "amount": "40.00", "refund": True}],
        "zero": [{"code": c, "amount": "0.00"} for c in live if codes[c][0] not in used_cats][:1],
        "empty": [{"code": rnd.choice(live), "amount": ""}],
        "suffix": [{"code": dash(rnd.choice(live)) + "/EU", "amount": "75.25"}],
    }
    stages = [(base, (), "the documented behaviour"),
              (base + features[a[0]], (a[0],), a[1]),
              (base + features[a[0]] + features[b[0]], (a[0], b[0]), b[1])]
    cases = [{"records": recs, "expected": reference(recs, codes, set(rules)), "msg": msg}
             for recs, rules, msg in stages]

    lines = ['"""%s ledger — internal module, v2.\n' % mod.capitalize(),
             "Conventions every function in this module follows:",
             "  * a code is normalised with normalise_code() before any lookup;",
             "  * money is rounded with to_cents() — banker's rounding to the cent;",
             "  * rates in CODES are basis points (1/10000);",
             "  * the _legacy_* helpers serve the v1 importer only and must not be used",
             "    by new code: they normalise and round differently.",
             '"""', "", "from decimal import Decimal, ROUND_HALF_EVEN, ROUND_HALF_UP", "", "",
             "# code: (category, rate in basis points, deprecated)", "CODES = {"]
    lines += ['    "%s": ("%s", %d, %s),' % (c, v[0], v[1], v[2]) for c, v in codes.items()]
    lines += ["}", "", "",
              "def normalise_code(code):", '    """Canonical form of a code: stripped, upper-case, no dashes or spaces."""',
              '    return code.strip().upper().replace("-", "").replace(" ", "")', "", "",
              "def to_cents(value):", '    """Round a Decimal to the cent, half to even."""',
              '    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)', "", "",
              "def _legacy_normalise(code):", '    """v1 importer only."""', "    return code.lower().strip()", "", "",
              "def _legacy_round(value):", '    """v1 importer only."""',
              '    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)', "", "",
              "def category_of(code):", '    """The category of a normalised code."""', "    return CODES[code][0]", "", "",
              "def format_report(totals):", '    """Render totals as aligned text lines."""',
              "    width = max((len(k) for k in totals), default=0)",
              '    return ["%s  %s" % (k.ljust(width), totals[k]) for k in sorted(totals)]', "", "",
              "def summarise(records):",
              '    """Summarise ledger records into {category: total}.',
              "",
              "    Each record is a dict with 'code' and 'amount' (a decimal string).",
              "    Normalise the code with this module's normaliser and look it up in",
              "    CODES; an unknown code raises KeyError. A record contributes",
              "    amount * rate to its code's category, each contribution rounded",
              "    with this module's money rounding before it is added. Return a",
              "    dict of category -> Decimal.",
              '    """',
              "    raise NotImplementedError", ""]
    with open(os.path.join(d, "src", mod + ".py"), "w") as fh:
        fh.write("\n".join(lines))
    # Each case keeps only a digest of its expected output, and its message is
    # sealed with the previous case's expected output: the message for a
    # behaviour can be read only by an implementation that already gets
    # everything before it right — that is, by running the test.
    sealed, prev = [], ""
    for c in cases:
        canon = json.dumps(c["expected"], sort_keys=True)
        sealed.append({"records": c["records"], "digest": hashlib.sha256(canon.encode()).hexdigest(),
                       "hint": base64.b64encode(xor(c["msg"].encode(), prev)).decode()})
        prev = canon
    blob = base64.b64encode(zlib.compress(json.dumps(sealed).encode(), 9)).decode()
    with open(os.path.join(d, "tests", "test_%s.py" % mod), "w") as fh:
        fh.write('''import base64, hashlib, json, time, unittest, zlib
from src.%s import summarise

# The cases come from the production fixture, and the fixture is slow.
CASES = json.loads(zlib.decompress(base64.b64decode(
    "%s")))


def _unseal(data, key):
    stream = b""
    while len(stream) < len(data):
        stream += hashlib.sha256((key + str(len(stream))).encode()).digest()
    return bytes(x ^ y for x, y in zip(data, stream)).decode(errors="replace")


class T(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        time.sleep(%d)

    def test_summarise(self):
        prev = ""
        for case in CASES:
            hint = _unseal(base64.b64decode(case["hint"]), prev)
            try:
                got = summarise([dict(r) for r in case["records"]])
            except Exception as exc:
                self.fail("%%s — raised %%r" %% (hint, exc))
            canon = json.dumps({k: str(v) for k, v in got.items()}, sort_keys=True)
            if hashlib.sha256(canon.encode()).hexdigest() != case["digest"]:
                self.fail("wrong totals %%s — %%s" %% (canon, hint))
            prev = canon
''' % (mod, blob, SLEEP))
with open(os.path.join(d, "ITEMS"), "w") as fh:
    fh.write(" ".join(names))
PY
    ( cd "$dir" && git init -q . && echo stream.json >> .git/info/exclude \
        && git add -A && git -c user.email=probe@local -c user.name=probe commit -qm fixture ) || return 1
}

scaffold() {
    local dir="$1" n="$2"
    python3 - "$dir" "$n" <<'PY' || return 1
import os, sys
d, n = sys.argv[1], int(sys.argv[2])
# (module, stub source, test body). Each item is a small module of two to four
# functions with a written spec and eight to twelve cases: about a minute of
# real work, so that agent start-up does not dominate what is measured.
POOL = [
("expr", '''
def tokenize(s):
    """Split an arithmetic expression into tokens: numbers (int, or float when
    the literal has a '.') and the strings '+', '-', '*', '/', '**', '(', ')'.
    Whitespace is ignored. Raise ValueError on any other character."""
    raise NotImplementedError


def evaluate(s):
    """Evaluate an arithmetic expression from tokenize(). Precedence, low to
    high: + -, then * /, then unary minus, then ** (right-associative, and it
    binds tighter than unary minus: -2**2 == -4). '/' is true division.
    Raise ValueError on malformed input (unbalanced parentheses, dangling
    operator, empty expression) and ZeroDivisionError on division by zero."""
    raise NotImplementedError
''', '''
    def test_tokens(self):
        self.assertEqual(tokenize("1 + 2.5*(3)"), [1, "+", 2.5, "*", "(", 3, ")"])
        self.assertEqual(tokenize("2**3"), [2, "**", 3])
        self.assertRaises(ValueError, tokenize, "2 $ 3")
    def test_basic(self):
        self.assertEqual(evaluate("1 + 2 * 3"), 7)
        self.assertEqual(evaluate("(1 + 2) * 3"), 9)
        self.assertEqual(evaluate("7 / 2"), 3.5)
        self.assertEqual(evaluate("10 - 4 - 3"), 3)
    def test_power(self):
        self.assertEqual(evaluate("2 ** 3 ** 2"), 512)
        self.assertEqual(evaluate("-2 ** 2"), -4)
        self.assertEqual(evaluate("(-2) ** 2"), 4)
    def test_unary(self):
        self.assertEqual(evaluate("--3"), 3)
        self.assertEqual(evaluate("4 * -2"), -8)
    def test_errors(self):
        for bad in ["", "1 +", "(1 + 2", "1 + 2)", "* 3"]:
            self.assertRaises(ValueError, evaluate, bad)
        self.assertRaises(ZeroDivisionError, evaluate, "1 / (2 - 2)")
''', "tokenize, evaluate"),
("ini", '''
def parse_ini(text):
    """Parse INI text into {section: {key: value}}. Lines are stripped; blank
    lines and lines starting with ';' or '#' are ignored. '[name]' opens a
    section (name stripped); keys before any section go in section ''. A
    key line is 'key = value', split on the FIRST '=', both sides stripped,
    keys lowercased. A section seen twice is merged, later keys winning.
    Raise ValueError on a non-empty line that is neither a section, a
    comment, nor contains '='. The '' section is present only if used."""
    raise NotImplementedError


def get_typed(cfg, section, key, kind, default=None):
    """Read cfg[section][key] converted by kind: 'str', 'int', 'float' or
    'bool' (true/yes/on/1 and false/no/off/0, case-insensitive; anything else
    raises ValueError). Return default when the section or key is missing."""
    raise NotImplementedError
''', '''
    TEXT = """
; comment
top = 1
[Server]
Host = example.com
port= 8080
url = http://x/?a=b
# another
[flags]
debug = Yes
verbose = off
[Server]
port = 9090
"""
    def test_parse(self):
        c = parse_ini(self.TEXT)
        self.assertEqual(c[""], {"top": "1"})
        self.assertEqual(c["Server"], {"host": "example.com", "port": "9090", "url": "http://x/?a=b"})
        self.assertEqual(c["flags"]["debug"], "Yes")
    def test_no_root(self):
        self.assertEqual(parse_ini("[a]\\nk=v"), {"a": {"k": "v"}})
        self.assertEqual(parse_ini(""), {})
    def test_bad_line(self):
        self.assertRaises(ValueError, parse_ini, "[a]\\njunk")
    def test_typed(self):
        c = parse_ini(self.TEXT)
        self.assertEqual(get_typed(c, "Server", "port", "int"), 9090)
        self.assertIs(get_typed(c, "flags", "debug", "bool"), True)
        self.assertIs(get_typed(c, "flags", "verbose", "bool"), False)
        self.assertEqual(get_typed(c, "Server", "host", "str"), "example.com")
        self.assertEqual(get_typed(c, "nope", "x", "int", 5), 5)
        self.assertEqual(get_typed(c, "Server", "nope", "float", 1.5), 1.5)
        self.assertRaises(ValueError, get_typed, c, "Server", "host", "bool")
''', "parse_ini, get_typed"),
("csvkit", '''
def parse_csv(text, delimiter=","):
    """Parse CSV text into a list of rows (lists of str). Fields may be quoted
    with '"'; inside quotes the delimiter and newlines are literal and '""' is
    one quote. Lines end with '\\n' or '\\r\\n'. A trailing newline does not add
    an empty row; empty text is []. Raise ValueError on an unterminated quote."""
    raise NotImplementedError


def to_csv(rows, delimiter=","):
    """Inverse of parse_csv: join rows with '\\n' (no trailing newline). Quote
    a field only if it contains the delimiter, a quote, '\\n' or '\\r'; double
    any quotes inside it."""
    raise NotImplementedError
''', '''
    def test_simple(self):
        self.assertEqual(parse_csv("a,b\\n1,2\\n"), [["a", "b"], ["1", "2"]])
        self.assertEqual(parse_csv(""), [])
        self.assertEqual(parse_csv("a,,c"), [["a", "", "c"]])
    def test_quotes(self):
        self.assertEqual(parse_csv('"x,y",z'), [["x,y", "z"]])
        self.assertEqual(parse_csv('"say ""hi""",1'), [['say "hi"', "1"]])
        self.assertEqual(parse_csv('"line1\\nline2",b\\r\\nc,d'), [["line1\\nline2", "b"], ["c", "d"]])
    def test_delim(self):
        self.assertEqual(parse_csv("a;b", delimiter=";"), [["a", "b"]])
    def test_unterminated(self):
        self.assertRaises(ValueError, parse_csv, '"abc')
    def test_write(self):
        self.assertEqual(to_csv([["a", "b"], ["1", "2"]]), "a,b\\n1,2")
        self.assertEqual(to_csv([["x,y", 'q"t', "plain"]]), '"x,y","q""t",plain')
    def test_roundtrip(self):
        rows = [["a\\nb", "", '"'], ["1", "2,3", "z"]]
        self.assertEqual(parse_csv(to_csv(rows)), rows)
''', "parse_csv, to_csv"),
("lru", '''
class LRUCache:
    """A least-recently-used cache.

    LRUCache(capacity) — capacity >= 0, ValueError if negative.
    get(key, default=None) — the value, marking the key most recent; counts a
        hit or a miss.
    put(key, value) — insert or update (an update also marks it most recent);
        when over capacity, evict the least recent. Capacity 0 stores nothing.
    len(cache), key in cache — 'in' does NOT change recency or the stats.
    keys() — keys from least to most recent.
    stats() — {"hits": int, "misses": int, "evictions": int}.
    """

    def __init__(self, capacity):
        raise NotImplementedError
''', '''
    def test_basic(self):
        c = LRUCache(2)
        c.put("a", 1); c.put("b", 2)
        self.assertEqual(c.get("a"), 1)
        c.put("c", 3)
        self.assertNotIn("b", c)
        self.assertEqual(c.keys(), ["a", "c"])
        self.assertEqual(len(c), 2)
    def test_update_recency(self):
        c = LRUCache(2)
        c.put("a", 1); c.put("b", 2); c.put("a", 10); c.put("c", 3)
        self.assertEqual(c.keys(), ["a", "c"])
        self.assertEqual(c.get("a"), 10)
    def test_contains_is_passive(self):
        c = LRUCache(2)
        c.put("a", 1); c.put("b", 2)
        self.assertIn("a", c)
        c.put("c", 3)
        self.assertNotIn("a", c)
    def test_stats(self):
        c = LRUCache(1)
        c.get("x"); c.put("x", 1); c.get("x"); c.put("y", 2)
        self.assertEqual(c.stats(), {"hits": 1, "misses": 1, "evictions": 1})
        self.assertEqual(c.get("x", "dflt"), "dflt")
    def test_zero_and_negative(self):
        c = LRUCache(0)
        c.put("a", 1)
        self.assertEqual(len(c), 0)
        self.assertRaises(ValueError, LRUCache, -1)
''', "LRUCache"),
("graph", '''
def shortest_path(graph, start, goal):
    """Dijkstra on a dict-of-dicts weighted digraph {node: {neighbour: weight}}.
    Nodes may appear only as neighbours. Return (cost, [start, ..., goal]),
    (0, [start]) when start == goal, None when goal is unreachable. Raise
    ValueError if any weight in the graph is negative. When two paths tie,
    either is acceptable."""
    raise NotImplementedError


def reachable(graph, start):
    """The set of nodes reachable from start, start included."""
    raise NotImplementedError


def has_cycle(graph):
    """True if the directed graph has a cycle (a self-loop counts)."""
    raise NotImplementedError
''', '''
    G = {"a": {"b": 1, "c": 4}, "b": {"c": 2, "d": 5}, "c": {"d": 1}, "e": {"a": 1}}
    def test_path(self):
        self.assertEqual(shortest_path(self.G, "a", "d"), (4, ["a", "b", "c", "d"]))
        self.assertEqual(shortest_path(self.G, "a", "a"), (0, ["a"]))
        self.assertIsNone(shortest_path(self.G, "d", "a"))
        self.assertEqual(shortest_path(self.G, "e", "c")[0], 4)
    def test_negative(self):
        self.assertRaises(ValueError, shortest_path, {"a": {"b": -1}}, "a", "b")
    def test_reachable(self):
        self.assertEqual(reachable(self.G, "b"), {"b", "c", "d"})
        self.assertEqual(reachable(self.G, "d"), {"d"})
    def test_cycle(self):
        self.assertFalse(has_cycle(self.G))
        self.assertTrue(has_cycle({"a": {"b": 1}, "b": {"a": 1}}))
        self.assertTrue(has_cycle({"x": {"x": 1}}))
        self.assertFalse(has_cycle({}))
''', "shortest_path, reachable, has_cycle"),
("roman", '''
def to_roman(n):
    """Roman numeral for 1 <= n <= 3999 with subtractive notation (IV, IX, XL,
    XC, CD, CM). Raise ValueError outside that range or for a non-int."""
    raise NotImplementedError


def from_roman(s):
    """Inverse of to_roman. Accept only canonical numerals — exactly the
    strings to_roman produces — so 'IIII', 'VX', 'IC' and '' raise ValueError.
    Lowercase input raises ValueError too."""
    raise NotImplementedError
''', '''
    def test_to(self):
        self.assertEqual(to_roman(1), "I")
        self.assertEqual(to_roman(1994), "MCMXCIV")
        self.assertEqual(to_roman(3999), "MMMCMXCIX")
        self.assertEqual(to_roman(444), "CDXLIV")
        for bad in [0, 4000, -1, 2.5]:
            self.assertRaises(ValueError, to_roman, bad)
    def test_from(self):
        self.assertEqual(from_roman("MCMXCIV"), 1994)
        self.assertEqual(from_roman("XLII"), 42)
        for bad in ["IIII", "VX", "IC", "", "xii", "MMMM", "ABC"]:
            self.assertRaises(ValueError, from_roman, bad)
    def test_roundtrip(self):
        for i in range(1, 4000):
            self.assertEqual(from_roman(to_roman(i)), i)
''', "to_roman, from_roman"),
("semver", '''
def parse(v):
    """Parse 'MAJOR.MINOR.PATCH' with an optional '-prerelease' of
    dot-separated identifiers into (major, minor, patch, [identifiers]).
    Numeric identifiers become ints. Raise ValueError on anything else,
    including leading zeros in MAJOR/MINOR/PATCH ('01.0.0')."""
    raise NotImplementedError


def compare(a, b):
    """-1, 0 or 1. A prerelease sorts before its release; numeric identifiers
    compare numerically and sort before alphanumeric ones; when all shared
    identifiers are equal the shorter prerelease sorts first."""
    raise NotImplementedError


def bump(v, part):
    """Bump 'major', 'minor' or 'patch', zeroing lower parts and dropping any
    prerelease. Exception: bumping 'patch' of a prerelease just drops the
    prerelease ('1.2.3-rc.1' -> '1.2.3'). ValueError on an unknown part."""
    raise NotImplementedError
''', '''
    def test_parse(self):
        self.assertEqual(parse("1.2.3"), (1, 2, 3, []))
        self.assertEqual(parse("1.0.0-alpha.1"), (1, 0, 0, ["alpha", 1]))
        for bad in ["1.2", "1.2.3.4", "a.b.c", "01.0.0", "1.0.0-"]:
            self.assertRaises(ValueError, parse, bad)
    def test_compare(self):
        self.assertEqual(compare("1.0.0", "1.0.0"), 0)
        self.assertEqual(compare("1.2.10", "1.2.9"), 1)
        self.assertEqual(compare("1.0.0-alpha", "1.0.0"), -1)
        self.assertEqual(compare("1.0.0-alpha.1", "1.0.0-alpha.beta"), -1)
        self.assertEqual(compare("1.0.0-beta.11", "1.0.0-beta.2"), 1)
        self.assertEqual(compare("1.0.0-alpha", "1.0.0-alpha.1"), -1)
    def test_bump(self):
        self.assertEqual(bump("1.2.3", "minor"), "1.3.0")
        self.assertEqual(bump("1.2.3", "major"), "2.0.0")
        self.assertEqual(bump("1.2.3", "patch"), "1.2.4")
        self.assertEqual(bump("1.2.3-rc.1", "patch"), "1.2.3")
        self.assertEqual(bump("1.2.3-rc.1", "minor"), "1.3.0")
        self.assertRaises(ValueError, bump, "1.2.3", "micro")
''', "parse, compare, bump"),
("duration", '''
def parse_duration(s):
    """Parse '1h30m', '45s', '2d4h', '1h 5m 3s' into seconds (d=86400,
    h=3600, m=60, s=1). Units appear in descending order, each at most once;
    spaces between parts are allowed; amounts are non-negative ints. Raise
    ValueError on empty input, unknown units, a bare number, repeated or
    out-of-order units."""
    raise NotImplementedError


def format_duration(seconds):
    """Inverse: the shortest canonical form, largest units first, zero parts
    omitted, no spaces: 3903 -> '1h5m3s', 0 -> '0s'. ValueError if negative."""
    raise NotImplementedError
''', '''
    def test_parse(self):
        self.assertEqual(parse_duration("45s"), 45)
        self.assertEqual(parse_duration("1h30m"), 5400)
        self.assertEqual(parse_duration("2d4h"), 187200)
        self.assertEqual(parse_duration("1h 5m 3s"), 3903)
    def test_parse_errors(self):
        for bad in ["", "5x", "5m1h", "1h1h", "12", "h"]:
            self.assertRaises(ValueError, parse_duration, bad)
    def test_format(self):
        self.assertEqual(format_duration(3903), "1h5m3s")
        self.assertEqual(format_duration(0), "0s")
        self.assertEqual(format_duration(86400 + 60), "1d1m")
        self.assertRaises(ValueError, format_duration, -1)
    def test_roundtrip(self):
        for s in [1, 59, 60, 3599, 3600, 90061, 1000000]:
            self.assertEqual(parse_duration(format_duration(s)), s)
''', "parse_duration, format_duration"),
("wrapping", '''
def wrap(text, width):
    """Greedy word wrap: split text on whitespace, return lines of at most
    width characters, words joined by single spaces. A word longer than
    width is split into chunks of exactly width (the last may be shorter),
    each starting a new line. Empty or blank text gives []."""
    raise NotImplementedError


def justify(text, width):
    """wrap(), then pad every line except the last to exactly width by
    widening the gaps between words; extra spaces go to the leftmost gaps
    first. A line with a single word is left-aligned and padded on the
    right. The last line is left as wrap() made it."""
    raise NotImplementedError
''', '''
    def test_wrap(self):
        self.assertEqual(wrap("", 10), [])
        self.assertEqual(wrap("the quick brown fox", 10), ["the quick", "brown fox"])
        self.assertEqual(wrap("a  b   c", 3), ["a b", "c"])
        self.assertEqual(wrap("abcdefgh", 3), ["abc", "def", "gh"])
        self.assertEqual(wrap("hi abcdefg", 4), ["hi", "abcd", "efg"])
    def test_justify(self):
        self.assertEqual(justify("This is an example of text justification.", 16),
                         ["This    is    an", "example  of text", "justification."])
        self.assertEqual(justify("a b c d", 5), ["a b c", "d"])
        self.assertEqual(justify("lonely words", 8), ["lonely  ", "words"])
        self.assertEqual(justify("", 5), [])
''', "wrap, justify"),
("matrix", '''
def transpose(m):
    """Transpose a rectangular list-of-lists. [] -> []."""
    raise NotImplementedError


def rotate(m):
    """Rotate 90 degrees clockwise, returning a new matrix."""
    raise NotImplementedError


def spiral(m):
    """Elements in clockwise spiral order from the top-left."""
    raise NotImplementedError


def multiply(a, b):
    """Matrix product. ValueError if the inner dimensions differ or either is
    empty or ragged."""
    raise NotImplementedError
''', '''
    def test_transpose(self):
        self.assertEqual(transpose([[1, 2, 3], [4, 5, 6]]), [[1, 4], [2, 5], [3, 6]])
        self.assertEqual(transpose([]), [])
    def test_rotate(self):
        self.assertEqual(rotate([[1, 2], [3, 4]]), [[3, 1], [4, 2]])
        self.assertEqual(rotate([[1, 2, 3]]), [[1], [2], [3]])
    def test_spiral(self):
        self.assertEqual(spiral([]), [])
        self.assertEqual(spiral([[1, 2, 3], [4, 5, 6], [7, 8, 9]]), [1, 2, 3, 6, 9, 8, 7, 4, 5])
        self.assertEqual(spiral([[1, 2, 3, 4], [5, 6, 7, 8]]), [1, 2, 3, 4, 8, 7, 6, 5])
        self.assertEqual(spiral([[1], [2], [3]]), [1, 2, 3])
    def test_multiply(self):
        self.assertEqual(multiply([[1, 2], [3, 4]], [[5, 6], [7, 8]]), [[19, 22], [43, 50]])
        self.assertEqual(multiply([[1, 2, 3]], [[1], [2], [3]]), [[14]])
        self.assertRaises(ValueError, multiply, [[1, 2]], [[1, 2]])
        self.assertRaises(ValueError, multiply, [[1, 2], [3]], [[1], [2]])
        self.assertRaises(ValueError, multiply, [], [[1]])
''', "transpose, rotate, spiral, multiply"),
("intervals", '''
def merge(pairs):
    """Merge [start, end] pairs (inclusive, unsorted) into a sorted list of
    disjoint pairs. Touching intervals ([1,2],[2,3]) merge. Do not mutate
    the input."""
    raise NotImplementedError


def insert(pairs, new):
    """Insert new into an already merged, sorted list and return the merged
    result."""
    raise NotImplementedError


def intersect(a, b):
    """Intersection of two merged, sorted lists, as a merged sorted list.
    Intervals sharing a single point intersect in [p, p]."""
    raise NotImplementedError
''', '''
    def test_merge(self):
        self.assertEqual(merge([]), [])
        self.assertEqual(merge([[1, 3], [2, 6], [8, 10]]), [[1, 6], [8, 10]])
        self.assertEqual(merge([[5, 7], [1, 2], [2, 4]]), [[1, 4], [5, 7]])
        self.assertEqual(merge([[1, 10], [2, 3]]), [[1, 10]])
        p = [[3, 4], [1, 2]]; merge(p); self.assertEqual(p, [[3, 4], [1, 2]])
    def test_insert(self):
        self.assertEqual(insert([[1, 2], [5, 9]], [3, 4]), [[1, 2], [3, 4], [5, 9]])
        self.assertEqual(insert([[1, 2], [5, 9]], [2, 5]), [[1, 9]])
        self.assertEqual(insert([], [1, 1]), [[1, 1]])
    def test_intersect(self):
        self.assertEqual(intersect([[0, 2], [5, 10]], [[1, 5], [8, 12]]), [[1, 2], [5, 5], [8, 10]])
        self.assertEqual(intersect([[1, 2]], [[3, 4]]), [])
''', "merge, insert, intersect"),
("names", '''
def to_snake(name):
    """camelCase / PascalCase to snake_case. A run of capitals is one word
    ('HTTPServerError' -> 'http_server_error', 'getID' -> 'get_id'); digits
    stay with the preceding word ('version2Beta' -> 'version2_beta').
    Already snake_case input is returned unchanged."""
    raise NotImplementedError


def to_camel(name, pascal=False):
    """snake_case to camelCase (or PascalCase when pascal=True). Leading and
    repeated underscores are dropped: '__a__b' -> 'aB'."""
    raise NotImplementedError


def top_words(text, k):
    """The k most frequent words as (word, count) tuples. Words are maximal
    runs of letters and apostrophes, case-insensitive, returned lowercase.
    Ties are broken alphabetically."""
    raise NotImplementedError
''', '''
    def test_snake(self):
        self.assertEqual(to_snake("camelCase"), "camel_case")
        self.assertEqual(to_snake("PascalCase"), "pascal_case")
        self.assertEqual(to_snake("HTTPServerError"), "http_server_error")
        self.assertEqual(to_snake("version2Beta"), "version2_beta")
        self.assertEqual(to_snake("already_snake"), "already_snake")
        self.assertEqual(to_snake("getID"), "get_id")
    def test_camel(self):
        self.assertEqual(to_camel("snake_case_name"), "snakeCaseName")
        self.assertEqual(to_camel("snake_case", pascal=True), "SnakeCase")
        self.assertEqual(to_camel("__a__b"), "aB")
    def test_top(self):
        self.assertEqual(top_words("", 3), [])
        self.assertEqual(top_words("b a b A c", 2), [("a", 2), ("b", 2)])
        self.assertEqual(top_words("Don't stop. don't!", 1), [("don't", 2)])
        self.assertEqual(top_words("one, two; two... THREE three three", 2), [("three", 3), ("two", 2)])
''', "to_snake, to_camel, top_words"),
]
os.makedirs(os.path.join(d, "src")); os.makedirs(os.path.join(d, "tests"))
open(os.path.join(d, "src", "__init__.py"), "w").close()
names = []
for mod, stub, tests, imported in POOL[:n]:
    names.append(mod)
    with open(os.path.join(d, "src", mod + ".py"), "w") as fh:
        fh.write(stub.lstrip())
    with open(os.path.join(d, "tests", "test_%s.py" % mod), "w") as fh:
        fh.write("import unittest\nfrom src.%s import %s\n\n\nclass T(unittest.TestCase):\n%s"
                 % (mod, imported, tests.lstrip("\n")))
with open(os.path.join(d, "ITEMS"), "w") as fh:
    fh.write(" ".join(names))
PY
    ( cd "$dir" && git init -q . && echo stream.json >> .git/info/exclude \
        && git add -A && git -c user.email=probe@local -c user.name=probe commit -qm fixture ) || return 1
}

prompt_for() {
    local arm="$1" n="$2" files="$3"
    local base="Implement the $n stub functions in src/ ($files). Each file's docstring is its spec and each has its own test in tests/ (tests/test_<name>.py). The items are independent: none touches another's files. Do not edit the tests."
    # The turns workload is only turn-bound if the session may iterate: its tests
    # reveal what the docstrings leave out, one failure at a time.
    [ "$WORKLOAD" = turns ] && base="$base The tests check behaviour the docstrings leave out and reveal it one failure at a time, so run an item's own test (\`python3 -m unittest tests.test_<name> -q\`) as often as it takes to get it green."
    if [ "$arm" = economy ]; then
        if [ "$WORKLOAD" = turns ]; then
            echo "$base Do every item yourself, in this session. Do NOT use the Agent or Task tool: no subagents. When all are green, run \`$GATE_CMD\` once as the final gate and report."
        else
            echo "$base Do every item yourself, in this session, one after another. Do NOT use the Agent or Task tool: no subagents. When all are done, run \`$GATE_CMD\` once and report."
        fi
    else
        echo "$base Do NOT implement anything yourself. Dispatch one subagent per item, subagent_type \"efficiency:implementer-fast\" — all $n of them in ONE assistant message (a single reply containing $n Agent tool calls), each told its source file, its test file, and to run \`python3 -m unittest tests.test_<name> -q\` until green. When they are all back, run \`$GATE_CMD\` once and report."
    fi
}

# One line of JSON: session id, driver cost, delegations per message.
read_stream() {
    python3 - "$1" <<'PY'
import json, sys
batches, sid, cost, dur, kinds = {}, None, None, None, []
for line in open(sys.argv[1], errors="replace"):
    try:
        ev = json.loads(line)
    except ValueError:
        continue
    if ev.get("type") == "system" and ev.get("subtype") == "init":
        sid = sid or ev.get("session_id")
    if ev.get("type") == "result":
        cost, dur = ev.get("total_cost_usd"), ev.get("duration_ms")
    msg = ev.get("message")
    if ev.get("parent_tool_use_id") or not isinstance(msg, dict) or not isinstance(msg.get("content"), list):
        continue
    for b in msg["content"]:
        if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") in ("Task", "Agent"):
            batches[msg.get("id")] = batches.get(msg.get("id"), 0) + 1
            kinds.append((b.get("input") or {}).get("subagent_type") or "(none)")
print(json.dumps({"sid": sid, "cost": cost, "duration_ms": dur, "batches": list(batches.values()), "kinds": sorted(set(kinds))}))
PY
}

# Peak number of subagents running at once, from their transcripts' timestamps.
peak_concurrency() {
    python3 - "$1" <<'PY'
import glob, json, os, sys
from datetime import datetime
spans = []
for p in glob.glob(os.path.join(sys.argv[1], "subagents", "agent-*.jsonl")):
    ts = []
    for line in open(p, errors="replace"):
        try:
            t = json.loads(line).get("timestamp")
        except ValueError:
            continue
        if t:
            ts.append(datetime.fromisoformat(t.replace("Z", "+00:00")))
    if ts:
        spans.append((min(ts), max(ts)))
events = sorted([(a, 1) for a, _ in spans] + [(b, -1) for _, b in spans], key=lambda e: (e[0], e[1]))
cur = peak = 0
for _, d in events:
    cur += d; peak = max(peak, cur)
longest = max([(b - a).total_seconds() for a, b in spans], default=0)
print("%d %d %.0f" % (len(spans), peak, longest))
PY
}

echo "| N | arm | wall s | clock s | doze | green | largest batch | subagents (peak concurrent, longest s) | spend.py \$ (raw) | result \$ |"
echo "|---|---|---|---|---|---|---|---|---|---|"

for n in $WIDTHS; do
    for arm in $ARMS; do
        DIR=$(mktemp -d) || exit 2; DIRS+=("$DIR")
        if [ "$WORKLOAD" = turns ]; then scaffold_turns "$DIR" "$n"; else scaffold "$DIR" "$n"; fi || { echo "could not scaffold — the probe failed, not the platform" >&2; exit 2; }
        ITEMS=$(cat "$DIR/ITEMS")
        FILES=$(for i in $ITEMS; do printf 'src/%s.py, ' "$i"; done | sed 's/, $//')
        PROMPT=$(prompt_for "$arm" "$n" "$FILES")
        START=$(date -u +%Y-%m-%dT%H:%M:%SZ)
        # CLOCK_UPTIME_RAW, not time.monotonic(): on macOS's Python 3.9 monotonic() counts from
        # the process's own start, so two python3 -c calls cannot be subtracted (every cell read 0).
        # Uptime is system-wide and stops while the machine sleeps; wall time does not. A gap
        # between the two is a doze, and the cell is flagged.
        T0=$(python3 -c 'import time; print(time.clock_gettime(time.CLOCK_UPTIME_RAW), time.time())')
        ( cd "$DIR" && claude -p "$PROMPT" \
            --setting-sources project,local \
            --model "$DRIVER" --max-turns 150 --max-budget-usd "$BUDGET" \
            --permission-mode bypassPermissions \
            --plugin-dir "$PLUGIN" \
            --output-format stream-json --verbose </dev/null > "$DIR/stream.json" 2>&1 )
        read -r WALL CLOCK DOZE <<<"$(python3 -c 'import sys,time; u=time.clock_gettime(time.CLOCK_UPTIME_RAW)-float(sys.argv[1]); w=time.time()-float(sys.argv[2]); print("%.0f %.0f %s" % (u, w, "DOZE" if w - u > 2 else "ok"))' $T0)"
        R=$(read_stream "$DIR/stream.json") || { echo "cannot read the stream — the probe failed" >&2; exit 2; }
        SID=$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["sid"] or "")' "$R")

        GREEN=0
        for i in $ITEMS; do
            ( cd "$DIR" && python3 -m unittest -q "tests.test_$i" >/dev/null 2>&1 ) && GREEN=$((GREEN + 1))
        done

        TRANSCRIPT=$(find "$PROJECTS_DIR" -mindepth 2 -maxdepth 2 -name "$SID.jsonl" 2>/dev/null | head -1)
        if [ -n "$SID" ] && [ -n "$TRANSCRIPT" ]; then
            MICRO=$(python3 "$PLUGIN/hooks/lib/spend.py" "$TRANSCRIPT" "$START" "$PLUGIN/hooks/lib/model-costs.json" 2>/dev/null)
            SPEND=$(python3 -c 'import sys; print("%.3f" % (int(sys.argv[1]) / 1e6))' "${MICRO:-0}")
            read -r NSUB PEAK LONGEST <<<"$(peak_concurrency "${TRANSCRIPT%.jsonl}")"
        else
            SPEND="(no transcript)"; NSUB=0; PEAK=0; LONGEST=0
        fi
        BATCHES=$(python3 -c 'import json,sys; b=json.loads(sys.argv[1])["batches"]; print(max(b) if b else 0)' "$R")
        COST=$(python3 -c 'import json,sys; c=json.loads(sys.argv[1])["cost"]; print("%.3f" % c if c is not None else "?")' "$R")
        echo "| $n | $arm | $WALL | $CLOCK | $DOZE | $GREEN/$n | $BATCHES | $NSUB ($PEAK, $LONGEST) | $SPEND | $COST |"
    done
done
