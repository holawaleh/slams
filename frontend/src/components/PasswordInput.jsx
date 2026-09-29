import { useState } from "react";

export default function PasswordInput({ id, value, onChange, autoComplete,
                                        invalid = false, ...rest }) {
  const [show, setShow] = useState(false);
  return (
    <div className="input-group"
         style={invalid ? { borderColor: "var(--bad)" } : undefined}>
      <span className="input-icon">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none"
             stroke="currentColor" strokeWidth="2">
          <rect x="3" y="11" width="18" height="11" rx="2" />
          <path d="M7 11V7a5 5 0 0 1 10 0v4" />
        </svg>
      </span>
      <input id={id} type={show ? "text" : "password"} value={value}
             autoComplete={autoComplete} onChange={onChange}
             aria-invalid={invalid || undefined} {...rest} />
      <button type="button" className="reveal" onClick={() => setShow(!show)}
              aria-label={show ? "Hide password" : "Show password"}
              title={show ? "Hide password" : "Show password"}>
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none"
             stroke="currentColor" strokeWidth="2">
          <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8S1 12 1 12z" />
          <circle cx="12" cy="12" r="3" />
          {show && <line x1="3" y1="21" x2="21" y2="3" />}
        </svg>
      </button>
    </div>
  );
}
