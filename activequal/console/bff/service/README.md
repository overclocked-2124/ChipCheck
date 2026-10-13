# ChipCheck BFF

This service implements `chipcheck.console.v1.ConsoleService` over gRPC. `PreviewProposedTests` forwards the configuration and available measured history to the Decision Service and returns its candidates in the console contract. It does not approve a setup, persist scientific data, or operate hardware.

From this directory:

```bash
npm ci
npm test
npm start
```

Start the Decision Service in `../../../decision/service` first. The default gRPC listener is `127.0.0.1:50051`, and the default Decision endpoint is `http://127.0.0.1:8001/v1/proposals`. Set `CHIPCHECK_BFF_LISTEN` or `CHIPCHECK_DECISION_URL` to change them. Run the console UI separately from `../../ui`.
