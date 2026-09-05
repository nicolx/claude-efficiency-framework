#!/usr/bin/env python3
"""Sum what a session has spent since a point in time, from its transcript.

    spend.py <transcript> <since-iso8601> <costs.json> [--by-model]

Prints an integer number of micro-dollars (1e-6 USD) — integers because the
caller is a shell script and shells cannot do float arithmetic. With
--by-model, prints JSON broken down by model instead.

Two things make this measurement possible at all, both verified rather than
assumed (docs/verified-platform-behaviour.md):

  * the Stop hook payload carries transcript_path, which the hook reference
    does not list for that event;
  * subagent turns are NOT in that transcript. `isSidechain` is in the schema
    and reads like a promise, but it was false on every row of a session that
    spawned three subagents. They live in a sibling directory instead, and on
    the session that produced this framework they were 17% of real spend.

Both are read, because the expensive half of a routed run is the delegated
half: a ceiling blind to subagents is a ceiling on the cheap work only.

Exit codes: 0 measured · 2 cannot measure (bad input, unreadable transcript).
A caller must treat 2 as "the guard is blind" and stop the run, not as zero.
"""

import glob
import json
import os
import re
import sys
from datetime import datetime, timezone

MICRO = 1_000_000
PER_TOKEN = 1_000_000  # prices are quoted per million tokens


def parse_ts(value):
    """ISO-8601 to aware datetime, or None. Accepts the trailing Z."""
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


DATE_SUFFIX = re.compile(r"-\d{8}$")


def normalise_model(model):
    """Strip the decorations a transcript puts on a model id.

    Two shapes appear in real transcripts and neither matches the price table
    as written: a context-window suffix (claude-opus-5[1m]) on the main
    session, and a dated snapshot (claude-haiku-4-5-20251001) on subagents.
    Missing either sends the id to the expensive fallback and inflates the
    measurement by up to 10x.
    """
    if not model:
        return None
    return DATE_SUFFIX.sub("", model.split("[", 1)[0])


def price_for(costs, model):
    models = costs["models"]
    bare = normalise_model(model)
    if bare and bare in models:
        return models[bare]
    return models[costs["default"]]


def transcripts_for(main_transcript):
    """The main transcript plus every subagent transcript of the same session.

    Subagent turns are NOT in the main transcript — there are no isSidechain
    rows there, measured. They live in a sibling directory named after the
    session:

        <dir>/<session>.jsonl              the main transcript
        <dir>/<session>/subagents/agent-*.jsonl

    Missing them makes the ceiling blind to exactly the spend it exists to
    watch, because delegating expensive review to a subagent is the whole
    point of routing.
    """
    paths = [main_transcript]
    base, ext = os.path.splitext(main_transcript)
    if ext == ".jsonl":
        paths.extend(sorted(glob.glob(os.path.join(base, "subagents", "agent-*.jsonl"))))
    return paths


def line_cost(usage, price):
    """Micro-dollars for one assistant message.

    Cache writes are billed per TTL and the transcript reports the split. When
    the breakdown is missing, everything is charged at the 1-hour rate: that is
    the higher of the two, so an unknown shape overestimates and the ceiling
    fires early rather than late.
    """
    dollars = 0.0
    dollars += usage.get("input_tokens", 0) * price["input"] / PER_TOKEN
    dollars += usage.get("output_tokens", 0) * price["output"] / PER_TOKEN
    dollars += usage.get("cache_read_input_tokens", 0) * price["cache_read"] / PER_TOKEN

    breakdown = usage.get("cache_creation")
    if isinstance(breakdown, dict):
        dollars += breakdown.get("ephemeral_5m_input_tokens", 0) * price["cache_write_5m"] / PER_TOKEN
        dollars += breakdown.get("ephemeral_1h_input_tokens", 0) * price["cache_write_1h"] / PER_TOKEN
    else:
        dollars += usage.get("cache_creation_input_tokens", 0) * price["cache_write_1h"] / PER_TOKEN

    return dollars


def main(argv):
    if len(argv) < 4:
        print(__doc__.strip().splitlines()[2].strip(), file=sys.stderr)
        return 2

    transcript, since_raw, costs_path = argv[1], argv[2], argv[3]
    by_model = "--by-model" in argv[4:]

    since = parse_ts(since_raw)
    if since is None:
        print("unparseable start timestamp: %r" % since_raw, file=sys.stderr)
        return 2

    try:
        with open(costs_path) as fh:
            costs = json.load(fh)
        if "models" not in costs or costs.get("default") not in costs.get("models", {}):
            raise ValueError("cost table has no usable default")
    except (OSError, ValueError) as exc:
        print("cannot read the cost table: %s" % exc, file=sys.stderr)
        return 2

    paths = transcripts_for(transcript)
    try:
        handles = [open(p, errors="replace") for p in paths]
    except OSError as exc:
        print("cannot read the transcript: %s" % exc, file=sys.stderr)
        return 2

    totals = {}
    for fh in handles:
      with fh:
        for raw in fh:
            raw = raw.strip()
            if not raw or raw[0] != "{":
                continue
            try:
                rec = json.loads(raw)
            except ValueError:
                # A transcript being written to can end in a partial line.
                # Skipping it under-reports by at most one message.
                continue

            message = rec.get("message")
            if not isinstance(message, dict):
                continue
            usage = message.get("usage")
            if not isinstance(usage, dict):
                continue

            when = parse_ts(rec.get("timestamp"))
            if when is None or when < since:
                continue

            model = normalise_model(message.get("model"))
            totals[model] = totals.get(model, 0.0) + line_cost(usage, price_for(costs, model))

    if by_model:
        print(json.dumps(
            {"total_micro_usd": round(sum(totals.values()) * MICRO),
             "by_model": {k or "unknown": round(v * MICRO) for k, v in sorted(totals.items(), key=lambda kv: -kv[1])}},
            indent=2))
    else:
        print(round(sum(totals.values()) * MICRO))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
