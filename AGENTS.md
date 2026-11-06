# Agent Reference

Use the HLD documents as the source of truth for project boundaries and design decisions. HLD 01 (`docs/01-activequal-system-context-and-platform-boundaries.md`) defines system context and service ownership; if it is absent from this checkout, consult `origin/main`. HLD 03 (`docs/03-activequal-episode-execution-and-safety-state-machine.md`) defines campaign and episode lifecycle and safety behavior. HLD 04 (`docs/04-activequal-test-contract-and-domain-model.md`) is the current initial draft; its open bench-specific limits and measurements need confirmation against the selected setup and are not formal safety approval.

## Test Setup Guidance

Use the PRD’s ESP32-S3 display-sensor OLED demo as the first concrete example, while allowing small setup changes. For each experiment, keep the chosen DUT, firmware, connected peripherals, controls, measurements, requirements, and safety limits clear. Decision chooses conditions from previous results; Agent manages the run and budget; Backend checks conditions against the limits and records results; Controller applies conditions, collects measurements, and returns the setup to a safe state; Oracle judges measured behavior. Record requested and measured values separately, and keep the demo’s hidden fault trigger separate from Decision’s inputs.

Record which setup produced each experiment. If hardware, firmware, or wiring changes, update affected controls, limits, and requirements before continuing. Keep earlier results linked to their original setup so comparability can be judged. Keep the model focused on this project’s small setups rather than designing a universal fixture framework.

## Stack

Application services (Backend, Agent, Decision, Oracle, Controller, Adapter) are Python, deployed as a control-plane process and a bench process, with a Next.js Console whose server routes replace a separate BFF (HLD 01 §2.1). The adaptive planners are multivariate TPE and GP-BO, with random as the baseline. Backend and Controller share one safety-rule library.
