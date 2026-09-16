"""Write the two hill-climb data files of the implementation plan from a real run.

  samples/pass1.data.json  — Phase 4: field grouping candidates (+ search stats)
  samples/pass2.data.json  — Phase 5: optimized Q&A JSON (+ search stats)
  samples/schema.json      — Phase 7: final field schema (template output, no LLM)

Run:  python eval/make_samples.py [path/to/form.pdf]
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ.setdefault("FORM_LLM_DISABLED", "1")

from app.main import hill_climb_data  # noqa: E402
from app.pipeline import pipeline  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "samples")


def main() -> int:
    src = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "fixtures", "forms", "hi_bank_form.pdf")
    doc = pipeline.run_on_file(src, "sample", os.path.basename(src), use_llm=False)
    assert doc.status == "done", doc.error
    os.makedirs(OUT, exist_ok=True)
    for name, payload in hill_climb_data(doc).items():
        fn = {"pass1": "pass1.data.json", "pass2": "pass2.data.json", "schema": "schema.json"}[name]
        with open(os.path.join(OUT, fn), "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print("wrote", fn)
    return 0


if __name__ == "__main__":
    sys.exit(main())
