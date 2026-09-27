import { useEffect } from "react";
import "./Modal.css";

export default function Modal({ title, onClose, children, width = 460 }) {
  useEffect(() => {
    const esc = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", esc);
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", esc);
      document.body.style.overflow = "";
    };
  }, [onClose]);

  return (
    <div className="modal-scrim" onMouseDown={onClose}>
      <div className="modal card" style={{ maxWidth: width }}
           onMouseDown={(e) => e.stopPropagation()}>
        <div className="spread modal-head">
          <h3 style={{ margin: 0 }}>{title}</h3>
          <button className="btn-ghost modal-x" onClick={onClose}
                  aria-label="Close">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none"
                 stroke="currentColor" strokeWidth="2">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}
