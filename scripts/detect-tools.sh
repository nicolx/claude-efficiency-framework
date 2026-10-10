#!/bin/bash
# detect-tools.sh — write the machine's operational tool inventory.
#
#   bash scripts/detect-tools.sh [project-root]
#
# Writes <project-root>/.efficiency/tools.md and prints a one-line summary.
#
# Why this exists: the expensive failure is not a missing tool, it is a PRESENT
# tool nobody knew about. Asked to pull text out of a PDF, a session that does
# not know `pdftotext` is installed writes a Python script with pypdf, fights the
# encodings, and spends thousands of tokens on what one command does in fifty.
#
# The inventory is per-MACHINE, not per-project, which is why it is gitignored: a
# colleague cloning the repo has a different machine, and a committed list that
# describes someone else's laptop is worse than no list at all.
#
# No network. Nothing is installed. This only looks.

set -uo pipefail

ROOT="${1:-$(pwd)}"
[ -d "$ROOT" ] || { echo "not a directory: $ROOT" >&2; exit 2; }
OUT_DIR="$ROOT/.efficiency"
OUT="$OUT_DIR/tools.md"

# name|what it replaces, in the words a model would recognise the need by
TOOLS="
pandoc|convert between document formats — markdown, docx, html, pdf, epub
soffice|LibreOffice headless: convert and render office documents
libreoffice|LibreOffice headless: convert and render office documents
pdftotext|extract text from a PDF (poppler)
pdftoppm|render PDF pages to images (poppler)
qpdf|split, merge, rotate, decrypt PDFs
gs|Ghostscript: compress and transform PDFs and PostScript
jq|query and transform JSON
yq|query and transform YAML and XML
mlr|Miller: query and reshape CSV, TSV and JSON records
qsv|fast CSV slicing, joining, statistics
xsv|fast CSV slicing, joining, statistics
sqlite3|query a SQLite database, and query CSV files as tables
ffmpeg|convert, trim and inspect audio and video
magick|ImageMagick: convert, resize and compose images
convert|ImageMagick: convert, resize and compose images
exiftool|read and write image and document metadata
rg|ripgrep: fast search across a tree
fd|fast file finding by name
sg|ast-grep: structural search and rewrite by syntax, not regex
gh|GitHub: pull requests, issues, releases, CI runs
glab|GitLab: merge requests, issues, pipelines
docker|run and build containers
curl|HTTP from the shell
unzip|read and extract zip archives
"

# ── tool_version <name> ──────────────────────────────────────────────────────
# Best-effort, and deliberately suspicious of what it gets back. Not every tool
# answers --version: poppler's pdftotext treats it as a FILENAME and replies
# "I/O Error: Couldn't open file '--version'", and unzip answers a flag warning.
# Printing either into the inventory would be noise in the one file whose job is
# to be believed, so output that looks like a complaint is thrown away and the
# tool is still listed as present — which is the fact that matters.
tool_version() {
    local name="$1" out=""
    for flag in --version -version -V -v; do
        out=$("$name" "$flag" 2>&1 | head -1 | tr -d '\r')
        case "$out" in
            ""|*[Ee]rror*|*rror:*|*caution:*|*"No such file"*|*nknown\ option*|            *nvalid\ option*|*[Uu]sage:*|*"not recognized"*)
                out="" ;;
            *)  break ;;
        esac
    done
    if [ -z "$out" ]; then
        printf 'version not reported'
    else
        printf '%.60s' "$out"
    fi
}

mkdir -p "$OUT_DIR" || { echo "cannot create $OUT_DIR" >&2; exit 2; }

present=""
absent=""
count=0

while IFS='|' read -r name purpose; do
    [ -z "$name" ] && continue
    if command -v "$name" >/dev/null 2>&1; then
        ver=$(tool_version "$name")
        present="$present- \`$name\` — $purpose · $ver
"
        count=$((count + 1))
    else
        absent="$absent- \`$name\` — $purpose
"
    fi
done <<< "$TOOLS"

{
    echo "# Operational tools on this machine"
    echo
    echo "Detected $(date +%Y-%m-%d) by \`scripts/detect-tools.sh\`. **Per-machine and gitignored**:"
    echo "a colleague's machine is a different machine, and a shared list describing someone else's"
    echo "laptop is worse than no list."
    echo
    echo "Re-run the script after installing anything, or when a tool here turns out to be missing."
    echo
    echo "## Available — use these instead of writing a script"
    echo
    printf '%s' "$present"
    echo
    echo "## Not installed"
    echo
    echo "Absence is not a problem until something needs one. When that happens, name the tool and"
    echo "offer to install it once, rather than reimplementing it."
    echo
    printf '%s' "$absent"
} > "$OUT" || { echo "cannot write $OUT" >&2; exit 2; }

echo "wrote $OUT — $count tool(s) available"
