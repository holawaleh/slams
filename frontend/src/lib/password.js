// Kept in step with backend/core/validators.py and the 10-character minimum
// in settings.AUTH_PASSWORD_VALIDATORS. The server is the final authority.
export const PASSWORD_RULES = [
  { label: "At least 10 characters", test: (p) => p.length >= 10 },
  { label: "An uppercase letter",    test: (p) => /[A-Z]/.test(p) },
  { label: "A lowercase letter",     test: (p) => /[a-z]/.test(p) },
  { label: "A number",               test: (p) => /[0-9]/.test(p) },
  { label: "A symbol (e.g. ! @ # -)", test: (p) => /[^A-Za-z0-9]/.test(p) },
  { label: "No spaces",              test: (p) => p.length > 0 && !/\s/.test(p) },
];

export const passwordOk = (p) => PASSWORD_RULES.every((r) => r.test(p));
