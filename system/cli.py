"""The command line: read one data folder, write one JSON line per hit.

    system/run <data_folder> <output_file> [--no-llm]

Reads nothing outside the folder it is given, writes nothing but the output file, and uses
only the Python standard library.
"""

import argparse
import collections
import json
import os
import sys
import time

from . import decide, loader, name_variants
from .model import DECISIONS

ENV_KEY = "OPENROUTER_API_KEY"


def build_parser():
    parser = argparse.ArgumentParser(
        prog="system/run",
        description="Decide, for every hit in the data folder, whether it is the customer.",
    )
    parser.add_argument("data_folder", help="the folder holding the JSON Lines tables")
    parser.add_argument("output_file", help="where to write one JSON line per hit")
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="never call the language model, even if %s is set" % ENV_KEY,
    )
    parser.add_argument(
        "--quiet", action="store_true", help="write nothing but the output file"
    )
    return parser


def llm_available(no_llm=False, env=None):
    """Whether the optional language-model fallback can run at all.

    The system is regex-only without it, so a missing key is not an error.
    """
    if no_llm:
        return False
    if env is not None:
        return bool(env.get(ENV_KEY, "").strip())
    try:
        from . import llm

        return bool(llm.api_key())
    except Exception:
        return bool(os.environ.get(ENV_KEY, "").strip())


def build_extractor(no_llm=False):
    """The optional language-model fallback, or None.

    The brief requires the system to run regex-only "if the key is missing or the API
    fails", so every way of not having one — no key, --no-llm, no module, a client that
    will not start — ends here as None rather than as an error.
    """
    if not llm_available(no_llm):
        return None
    try:
        from . import llm

        client = llm.build()
        return llm.Extractor(client) if client is not None else None
    except Exception:
        return None


def run(data_folder, output_file, no_llm=False, quiet=False, out=sys.stdout):
    started = time.time()
    data = loader.load(data_folder)
    variants = (
        name_variants.from_raw(data.name_variants_raw) if data.name_variants_raw else None
    )
    extractor = build_extractor(no_llm)

    engine = decide.build(data, variants, extractor=extractor)
    decisions = engine.decide_all()

    parent = os.path.dirname(os.path.abspath(output_file))
    if parent and not os.path.isdir(parent):
        os.makedirs(parent)
    with open(output_file, "w", encoding="utf-8") as fh:
        for decision in decisions:
            fh.write(json.dumps(decision.to_json(), ensure_ascii=False) + "\n")

    if not quiet:
        _report(decisions, data, output_file, time.time() - started, extractor, out)
    return decisions


def _report(decisions, data, output_file, seconds, extractor, out):
    counts = collections.Counter(d.decision for d in decisions)
    total = len(decisions) or 1
    print("%d hits -> %s in %.1fs" % (len(decisions), output_file, seconds), file=out)
    print(
        "  %s"
        % "  ".join(
            "%s %d (%.1f%%)" % (name, counts[name], 100.0 * counts[name] / total)
            for name in DECISIONS
            if counts[name]
        ),
        file=out,
    )
    codes = collections.Counter(d.reason_code for d in decisions)
    print("  %s" % ", ".join("%s %d" % (c, n) for c, n in codes.most_common()), file=out)
    failed = [d.hit_id for d in decisions if d.note]
    if failed:
        print("  %d hits could not be checked and were left for review: %s"
              % (len(failed), ", ".join(failed[:5])), file=out)
    if extractor is None:
        print("  language model: not used (regex only)", file=out)
    else:
        print("  language model: %s %s" % (extractor.model, extractor.usage.summary()), file=out)


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        run(args.data_folder, args.output_file, args.no_llm, args.quiet)
    except loader.DataError as error:
        print("could not read the data folder: %s" % error, file=sys.stderr)
        return 2
    return 0
