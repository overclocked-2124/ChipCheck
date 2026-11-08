# ActiveQual Console

Next.js researcher console (HLD 09). Its server routes (`/api/cp/*`, `/api/stream/*`) replace a separate BFF
(HLD 01 §2.1): they add the operator token server-side and forward the reviewer passphrase for one request only.

```bash
npm ci
ACTIVEQUAL_URL=http://127.0.0.1:8001 \
ACTIVEQUAL_OPERATOR_TOKEN_FILE=~/.config/activequal/operator.token \
npm run dev            # listens on 127.0.0.1:3000 only (HLD 07 §11)
npm test && npm run typecheck && npm run build
```

Pages: campaigns (list, new, live view with arming checklist and lockout clearing, results with export),
contracts (editor, versions, approval), fixtures (health, calibration, token rotation), compare.
Known gaps: no manual-candidate page; the live page polls instead of using the SSE route.
