# ChipCheck Console

The console collects a test setup in five steps: setup identity, controllable inputs, required evidence, reviewed limits and budget, then review. It calls the BFF's protobuf RPC to retrieve proposed tests. The current BFF response is labeled as a mock preview. The console does not select candidates, check bench safety, or execute hardware.

Run with Node.js 20 or newer:

```bash
npm ci
npm run dev
```

Start the BFF first from `../bff/service`, then open http://localhost:3000. Set `CHIPCHECK_BFF_ADDRESS` if the BFF is not listening on `127.0.0.1:50051`. Use `npm run build` to verify a production build.
