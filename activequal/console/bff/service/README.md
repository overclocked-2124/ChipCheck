# ChipCheck BFF

This service implements `chipcheck.console.v1.ConsoleService` over gRPC. The current `PreviewProposedTests` response uses labeled mock examples. It does not select real tests, approve a setup, persist scientific data, or operate hardware.

From this directory:

```bash
npm ci
npm test
npm start
```

The default listener is `127.0.0.1:50051`. Set `CHIPCHECK_BFF_LISTEN` to change it. Run the console UI separately from `../../ui`.
