"""Test mode: `python -m simplifier --file tests/samples/example.json` prints one response JSON."""

import argparse
import json
import sys
from pathlib import Path

from .api.schemas import SimplifyRequest, SimplifyResponse
from .core.pipeline import error_response, run


def simplify_file(path: Path) -> SimplifyResponse:
    case_id = ""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            case_id = str(raw.get("case_id", ""))
        request = SimplifyRequest.model_validate(raw)
    except Exception as exc:
        return error_response(case_id, f"invalid request file: {type(exc).__name__}: {exc}")
    return run(request)


def main() -> int:
    parser = argparse.ArgumentParser(prog="simplifier", description=__doc__)
    parser.add_argument("--file", required=True, type=Path, help="request JSON for one voted motie")
    args = parser.parse_args()

    response = simplify_file(args.file)

    # The Windows console is not UTF-8 by default; the response is.
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(response.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 1 if response.error else 0


if __name__ == "__main__":
    sys.exit(main())
