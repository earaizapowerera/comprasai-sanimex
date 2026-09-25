/** Aviso temporal (badge) de la pantalla Sugeridos. */
export default function Toast({ toast }) {
  return (
    <div
      className={`badge badge--${toast.kind === "danger" ? "danger" : toast.kind === "success" ? "success" : "neutral"}`}
      style={{ marginBottom: 16, height: "auto", padding: "8px 14px", display: "block" }}
    >
      {toast.text}
    </div>
  );
}
