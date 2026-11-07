# ChipCheck Console

The console collects a test setup in five steps: setup identity, controllable inputs, required evidence, reviewed limits and budget, then review. Its Next.js route (`/api/proposals`) acts as the backend-for-frontend and retrieves candidates from the Decision Service over HTTP; there is no separate BFF service. The console does not approve candidates, check bench safety, or execute hardware.

Run with Node.js 20 or newer:

```bash
npm ci
npm run dev
```

Start the Decision Service from the repository root with `python -m activequal.decision.service.decision`, then open http://localhost:3000. Set `CHIPCHECK_DECISION_URL` if the Decision Service is not at `http://127.0.0.1:8001/v1/proposals`. Use `npm run build` to verify a production build. Without measured history, TPE produces startup proposals. Adaptive selection begins only after the caller supplies measured outcomes and robustness values.
