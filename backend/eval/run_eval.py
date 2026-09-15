"""Phase 10 — evaluation harness.

Metrics
* form-gate accuracy            (false accepts / false rejects)
* grouping recall  (Pass 1)     ground-truth labels found among candidates
* pruning precision / recall    (Pass 2) kept genuine fields, dropped junk
* template hit-rate             how many kept fields got a canonical question
* final answer accuracy         (only for fields with a ground-truth value)

Run:  python eval/run_eval.py [--llm] [--verbose]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from app.pipeline import form_gate, grouping, ocr, preprocess, pruning, llm  # noqa: E402
from app.pipeline.templates import normalize_label  # noqa: E402
from app.schemas import QADocument  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


def load_pages(pdf: str):
    imgs = preprocess.preprocess_file(pdf, do_deskew=False)
    return ocr.run_ocr(imgs, backend="pdftext")


def label_match(a: str, b: str) -> bool:
    na, nb = normalize_label(a), normalize_label(b)
    if not na or not nb:
        return False
    return na == nb or na in nb or nb in na


def eval_form(pdf: str, gt: dict, use_llm: bool, verbose: bool) -> dict:
    pages = load_pages(pdf)
    gate = form_gate.run_form_gate(pages)
    res = {"name": gt["name"], "gate_ok": gate.is_form, "gate_score": gate.confidence}
    if not gate.is_form:
        res.update(group_recall=0.0, prune_precision=0.0, prune_recall=0.0, junk_dropped=0.0, template_rate=0.0)
        return res
    per_page = {}
    cands_all = []
    for p in pages:
        c, _ = grouping.group_page(p)
        per_page[p.number] = c
        cands_all.extend(c)
    truth = gt["fields"]
    found = sum(1 for t in truth if any(label_match(t["label"], c.label_text) for c in cands_all))
    res["group_recall"] = found / max(len(truth), 1)

    qa, _ = pruning.build_qa_document(pages, per_page, gate.confidence)
    kept = qa.fields
    tp = sum(1 for t in truth if any(label_match(t["label"], k.original_label) for k in kept))
    genuine_kept = sum(1 for k in kept if any(label_match(t["label"], k.original_label) for t in truth))
    junk_kept = sum(1 for k in kept if any(label_match(j, k.original_label) or normalize_label(k.original_label) in normalize_label(j)
                                           for j in gt["junk"]) and not any(label_match(t["label"], k.original_label) for t in truth))
    res["prune_recall"] = tp / max(len(truth), 1)
    res["prune_precision"] = genuine_kept / max(len(kept), 1)
    res["junk_kept"] = junk_kept
    res["kept"] = len(kept)
    res["removed"] = qa.junk_candidates_removed
    res["template_rate"] = sum(1 for k in kept if k.template_key) / max(len(kept), 1)

    # Answer accuracy on pre-filled values.
    with_vals = [t for t in truth if t.get("value")]
    if with_vals:
        fields, _ = llm.extract_with_llm(qa, use_llm=use_llm)
        ok = 0
        for t in with_vals:
            exact = [f for f in fields if normalize_label(f.label_original_language) == normalize_label(t["label"])]
            loose = [f for f in fields if label_match(t["label"], f.label_original_language)]
            for f in exact or loose:
                if True:
                    if t["value"].replace(",", "") in f.value.replace(",", "") or f.value.replace(",", "") in t["value"].replace(",", ""):
                        ok += 1
                    break
        res["answer_acc"] = ok / len(with_vals)
    if verbose:
        print(f"\n== {gt['name']}  gate={gate.confidence}  kept={len(kept)} removed={qa.junk_candidates_removed}")
        for k in kept:
            flag = "" if any(label_match(t["label"], k.original_label) for t in truth) else "   <-- not in GT"
            print(f"   [{k.expected_answer_type.value:15}] {k.original_label!r:40} -> {k.question}{flag}")
        missing = [t["label"] for t in truth if not any(label_match(t["label"], k.original_label) for k in kept)]
        if missing:
            print("   MISSING:", missing)
    return res


def eval_non_form(pdf: str, gt: dict) -> dict:
    pages = load_pages(pdf)
    gate = form_gate.run_form_gate(pages)
    return {"name": gt["name"], "gate_ok": not gate.is_form, "gate_score": gate.confidence, "signals": gate.signals}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", action="store_true", help="use the LLM for the answer-accuracy metric")
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args()
    t0 = time.time()
    forms, nonforms = [], []
    for j in sorted(glob.glob(os.path.join(HERE, "fixtures", "forms", "*.json"))):
        gt = json.load(open(j, encoding="utf-8"))
        forms.append(eval_form(j[:-5] + ".pdf", gt, args.llm, args.verbose))
    for j in sorted(glob.glob(os.path.join(HERE, "fixtures", "non_forms", "*.json"))):
        gt = json.load(open(j, encoding="utf-8"))
        r = eval_non_form(j[:-5] + ".pdf", gt)
        nonforms.append(r)
        if args.verbose and not r["gate_ok"]:
            print(f"FALSE ACCEPT {r['name']} score={r['gate_score']} {r['signals']}")

    def avg(rows, k):
        vals = [r[k] for r in rows if k in r]
        return sum(vals) / len(vals) if vals else float("nan")

    gate_acc = (sum(r["gate_ok"] for r in forms) + sum(r["gate_ok"] for r in nonforms)) / (len(forms) + len(nonforms))
    print("\n==== RESULTS ====")
    print(f"documents: {len(forms)} forms, {len(nonforms)} non-forms   ({time.time() - t0:.1f}s)")
    print(f"form-gate accuracy      : {gate_acc:.3f}   (false rejects: {sum(not r['gate_ok'] for r in forms)}, "
          f"false accepts: {sum(not r['gate_ok'] for r in nonforms)})")
    print(f"pass-1 grouping recall  : {avg(forms, 'group_recall'):.3f}")
    print(f"pass-2 pruning recall   : {avg(forms, 'prune_recall'):.3f}")
    print(f"pass-2 pruning precision: {avg(forms, 'prune_precision'):.3f}   (junk kept total: {sum(r.get('junk_kept', 0) for r in forms)})")
    print(f"template hit-rate       : {avg(forms, 'template_rate'):.3f}")
    print(f"answer accuracy         : {avg(forms, 'answer_acc'):.3f}   (llm={'on' if args.llm else 'off'})")
    print("\nper-form:")
    for r in forms:
        print(f"  {r['name']:24} gate={r['gate_score']:.2f} grp={r.get('group_recall', 0):.2f} "
              f"prec={r.get('prune_precision', 0):.2f} rec={r.get('prune_recall', 0):.2f} kept={r.get('kept', 0)} rm={r.get('removed', 0)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
