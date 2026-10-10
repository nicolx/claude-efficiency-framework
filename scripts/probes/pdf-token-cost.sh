#!/bin/bash
# pdf-token-cost.sh — what does it actually cost to read a PDF into a session?
#
# The claims in docs/verified-platform-behaviour.md § 13 rest on this probe.
#
#   bash scripts/probes/pdf-token-cost.sh make                  # build the test PDF
#   bash scripts/probes/pdf-token-cost.sh measure <transcript>  # read the cost back
#
# The measurement cannot be taken by a script alone: nothing outside a live
# session can make Claude Code read a PDF. So this is a two-halves probe, the
# same shape as statusline.sh — `make` builds a document with a known page count
# and a known character count, you read it in a session, and `measure` recovers
# what that cost from the transcript the session wrote.
#
# Method, and its error term. A tool result's cost is the context growth of the
# turn that follows it: `cache_creation_input_tokens` of the next assistant
# message, minus the `output_tokens` of the assistant message that called the
# tool, since those enter the context too. The subtraction is the error term —
# it is exact only if every output token is retained, so take the measurement
# from a turn whose assistant message was SHORT. The 5-page figure in § 13 was
# taken after a 184-token message; the single-page figure after a 2,213-token
# one, which is why the two do not divide evenly.
#
# What it never prints: conversation content. Sizes, token counts and tool
# names only.

set -uo pipefail

MODE="${1:-}"
OUT_DIR="${TMPDIR:-/tmp}/pdf-token-cost"

usage() {
    echo "usage: bash scripts/probes/pdf-token-cost.sh make" >&2
    echo "       bash scripts/probes/pdf-token-cost.sh measure <path-to-transcript.jsonl>" >&2
    exit 2
}

# ── make ─────────────────────────────────────────────────────────────────────
# A deliberately BORING document: dense, uniform rows, and a final page holding
# seven lines on an otherwise empty sheet. That last page is the whole point —
# it is what shows whether the cost follows the content or the page count.
make_pdf() {
    mkdir -p "$OUT_DIR" || exit 2
    local txt="$OUT_DIR/doc.txt" pdf="$OUT_DIR/doc.pdf"

    python3 - > "$txt" <<'PY'
rows = []
for page in range(1, 6):
    rows.append("Section %d: Quarterly operations report\n" % page)
    for i in range(50):
        rows.append("  line %02d  metric_%02d   value %4d   delta %3d   status %s\n"
                    % (i, i, i * 37 % 991, i * 13 % 77, "ok" if i % 3 else "review"))
print("".join(rows))
PY

    # cupsfilter is macOS-only and is used here because it needs nothing
    # installed. Anything that turns text into a multi-page PDF will do; what
    # matters is that the last page is nearly empty.
    if command -v cupsfilter >/dev/null 2>&1; then
        cupsfilter "$txt" > "$pdf" 2>/dev/null
    elif command -v pandoc >/dev/null 2>&1; then
        pandoc "$txt" -o "$pdf" 2>/dev/null
    else
        echo "error: no cupsfilter (macOS) and no pandoc — cannot build the test PDF" >&2
        exit 2
    fi
    [ -s "$pdf" ] || { echo "error: the PDF came out empty" >&2; exit 2; }

    local chars pages
    chars=$(wc -c < "$txt" | tr -d ' ')
    pages=$(pdfinfo "$pdf" 2>/dev/null | awk '/^Pages:/ {print $2}')

    echo "built  $pdf"
    echo "       ${pages:-?} pages, $chars characters of source text"
    echo
    echo "Now, in a live session:"
    echo "  1. Read it as a PDF:   Read($pdf, pages=\"1-${pages:-5}\")"
    echo "  2. Read the last page alone — it holds 7 lines:  Read(..., pages=\"${pages:-5}\")"
    echo "  3. Read the same content as text:  pdftotext -layout $pdf - "
    echo "  4. Then: bash scripts/probes/pdf-token-cost.sh measure <this session's transcript>"
    echo
    echo "Keep the messages around each read SHORT — the assistant's own output"
    echo "tokens are subtracted out, and that subtraction is the error term."
}

# ── measure ──────────────────────────────────────────────────────────────────
measure() {
    local transcript="$1"
    [ -f "$transcript" ] || { echo "error: $transcript is not a file" >&2; exit 2; }

    python3 - "$transcript" <<'PY'
import json, sys

rows = []
for line in open(sys.argv[1], errors="replace"):
    line = line.strip()
    if not line:
        continue
    try:
        rows.append(json.loads(line))
    except ValueError:
        continue

# Claude Code writes one transcript row per content block, so the same assistant
# message appears two or three times carrying identical usage. Counting those
# twice would double every figure in the report.
seen, msgs = set(), []
for r in rows:
    m = r.get("message") or {}
    kind = r.get("type")
    if kind == "assistant" and m.get("usage"):
        key = m.get("id") or (r.get("timestamp"), m["usage"].get("output_tokens"))
        if key in seen:
            # merge the content blocks of a message already recorded
            for b in (m.get("content") or []):
                if isinstance(b, dict) and b.get("type") == "tool_use":
                    msgs[-1]["calls"].append(b)
            continue
        seen.add(key)
        msgs.append({
            "kind": "assistant",
            "usage": m["usage"],
            "calls": [b for b in (m.get("content") or [])
                      if isinstance(b, dict) and b.get("type") == "tool_use"],
        })
    elif kind == "user":
        size = 0
        for b in (m.get("content") or []):
            if isinstance(b, dict) and b.get("type") == "tool_result":
                size += len(json.dumps(b.get("content")))
        if size:
            msgs.append({"kind": "result", "bytes": size})

print("%-26s %10s %12s %10s" % ("tool result", "bytes", "tokens", "per page"))
print("-" * 62)

found = 0
for i, m in enumerate(msgs):
    if m["kind"] != "result":
        continue
    before = msgs[i - 1] if i and msgs[i - 1]["kind"] == "assistant" else None
    after = None
    for n in msgs[i + 1:]:
        if n["kind"] == "assistant":
            after = n
            break
    if not before or not after:
        continue

    cost = after["usage"].get("cache_creation_input_tokens", 0) \
        - before["usage"].get("output_tokens", 0)
    call = before["calls"][0] if before["calls"] else {}
    name = call.get("name", "?")
    args = call.get("input") or {}
    path = str(args.get("file_path", ""))
    pages = str(args.get("pages", ""))

    if name == "Read" and path.lower().endswith(".pdf"):
        label = "Read PDF pages=%s" % (pages or "all")
        n_pages = 0
        for part in pages.split(","):
            part = part.strip()
            if "-" in part:
                a, _, b = part.partition("-")
                try:
                    n_pages += int(b) - int(a) + 1
                except ValueError:
                    pass
            elif part.isdigit():
                n_pages += 1
        per = "%d" % (cost / n_pages) if n_pages and cost > 0 else "-"
    else:
        label = name
        per = "%.2f c/tok" % (m["bytes"] / cost) if cost > 0 else "-"

    print("%-26s %10d %12d %10s" % (label[:26], m["bytes"], cost, per))
    found += 1

print()
if not found:
    print("No measurable tool results found. Was this the session that did the reads?")
    sys.exit(2)
print("A PDF page costs what it costs whatever is printed on it: compare a full")
print("page against the nearly-empty last one. For text results the last column")
print("is characters per token — the number that decides whether converting a")
print("page to Markdown is cheaper than looking at it.")
PY
}

case "$MODE" in
    make)    make_pdf ;;
    measure) [ $# -ge 2 ] || usage; measure "$2" ;;
    *)       usage ;;
esac
