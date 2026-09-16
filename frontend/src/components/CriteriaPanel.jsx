import { useEffect, useState } from "react";
import { Modal } from "./ui";

import { API_BASE as BASE } from "../config";

/** "What counts as a form?" — the acceptance criteria the gate applies. */
export default function CriteriaPanel({ open, onClose }) {
  const [data, setData] = useState(null);
  useEffect(() => {
    if (open) fetch(`${BASE}/criteria`).then((r) => r.json()).then(setData).catch(() => setData({ criteria: [] }));
  }, [open]);
  return (
    <Modal open={open} onClose={onClose} title="What counts as a form?" subtitle="Only files that meet these criteria are accepted. Everything else is rejected before any extraction." width="max-w-xl">
        <ol className="flex flex-col gap-2 text-sm">
          {(data?.criteria || []).map((c, i) => (
            <li key={i} className={`flex gap-3 rounded-xl p-3 ${c.startsWith("NOT") ? "bg-rose-500/10 text-rose-200  " : "bg-white/5 "}`}>
              <span className="font-semibold text-neutral-500">{i + 1}</span>
              <span>{c}</span>
            </li>
          ))}
          {!data && <li className="muted">Loading…</li>}
        </ol>
        <div className="muted mt-4 text-xs">
          How it is checked: language-independent layout signals first (separators, blanks, boxes, short label rows); scans and borderline cases are confirmed by the
          <b> form check provider</b>{data?.gate_provider ? ` (${data.gate_provider})` : ""} looking at the page image.
        </div>
    </Modal>
  );
}
