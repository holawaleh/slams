export const MIN_LENGTH = 8;

// Kept in step with backend/core/validators.py and the 8-character minimum
// in settings.AUTH_PASSWORD_VALIDATORS. The server is the final authority.
export const PASSWORD_RULES = [
  { label: `At least ${MIN_LENGTH} characters`, test: (p) => p.length >= MIN_LENGTH },
  { label: "An uppercase letter",    test: (p) => /[A-Z]/.test(p) },
  { label: "A lowercase letter",     test: (p) => /[a-z]/.test(p) },
  { label: "A number",               test: (p) => /[0-9]/.test(p) },
  { label: "A symbol (e.g. ! @ # -)", test: (p) => /[^A-Za-z0-9]/.test(p) },
  { label: "No spaces",              test: (p) => p.length > 0 && !/\s/.test(p) },
];

export const passwordOk = (p) => PASSWORD_RULES.every((r) => r.test(p));

// The rules a password still fails, named so the message can say which.
export const missingRules = (p) =>
  PASSWORD_RULES.filter((r) => !r.test(p)).map((r) => r.label.toLowerCase());
