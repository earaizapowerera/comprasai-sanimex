import { useEffect, useState } from "react";

export function SkeletonList() {
  return (
    <div className="pb-list">
      {[0, 1, 2].map((i) => (
        <div className="card" key={i}>
          <span className="skeleton skeleton--text" style={{ width: "40%" }} />
          <span className="skeleton skeleton--text" style={{ width: "70%" }} />
          <span className="skeleton" style={{ width: "100%", height: 48, marginTop: 12 }} />
        </div>
      ))}
    </div>
  );
}

export function ToastBanner({ toast }) {
  if (!toast) return null;
  return (
    <div
      className={`badge badge--${toast.kind === "danger" ? "danger" : toast.kind === "success" ? "success" : "neutral"}`}
      style={{ marginBottom: 16, height: "auto", padding: "8px 14px", display: "block" }}
    >
      {toast.text}
    </div>
  );
}

/** Toast que se autodescarta a los 4 s (Grid 1 y Grid 2). */
export function useAutoDismissToast() {
  const [toast, setToast] = useState(null);
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 4000);
    return () => clearTimeout(t);
  }, [toast]);
  return [toast, setToast];
}

export function Metric({ label, value, tone, strong }) {
  const toneClass = tone === "ok" ? "text-success" : tone === "warn" ? "text-warn" : tone === "danger" ? "text-danger" : "";
  return (
    <div className="pb-metric">
      <span className="caption">{label}</span>
      <span className={`tnum ${strong ? "body" : "footnote"} ${toneClass}`} style={strong ? { fontWeight: 700 } : {}}>
        {value}
      </span>
    </div>
  );
}
