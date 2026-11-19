# Claude Code — Start Here

The complete authoritative requirements are in `docs/PhaseForgeStudio_MASTER_SPEC.md`. Read the **entire file**, not just its first screen or a summary, and preserve all six original specifications.

Repository: https://github.com/ichasekatz/PhaseForgeStudio

My decision is to implement **ALL** of the requirements. This is not a request to choose A/B/C/D or reduce the scope. Execute in dependency order, incrementally and with tests, across as many sessions as necessary. Do not claim autonomous continuation after the session ends.

**Do now:**
1. Check the current repository, installed versions, existing PAIPAI/ORCHID stubs, and current working tree. Preserve existing data and changes.
2. Read the full master specification and create/update `docs/FRAMEWORK_FEATURE_AUDIT.md`, a machine-readable exhaustive feature ledger, `docs/IMPLEMENTATION_ROADMAP.md`, and `docs/IMPLEMENTATION_PROGRESS.md`. Every requirement must be traceable to an ID and a test/evidence status.
3. Start coding the first unblocked, dependency-priority implementation task **in this session**; run tests; fix failures; commit/checkpoint. Do not stop at an audit or plan.
4. Continue progressing through tasks as capacity allows, saving exact state and next steps at every session boundary. On restart, read the ledger and continue at the next uncompleted feature; do not reimplement finished features.
5. Once the implementation is complete, run genuine end-to-end GUI/backend/scientific tests and produce `docs/FINAL_VALIDATION_REPORT.md` and `docs/USER_ACCEPTANCE_TESTING.md`.

**Reporting:** At the end of each session summarize implemented features, tests with actual evidence, blockers, changed files, commits, and the exact next task. Do not state “finished” until all verifiable requirements pass. Label blocked HPC, network, or unavailable model-dependent steps honestly.

Do not spend expensive HPC/cloud resources or perform destructive repository operations without appropriate authorization. Avoid speculative upstream APIs, placeholder tabs, or fake scientific validation.

If you have a workflow/multi-agent tool available, use it for independent audits and tests, while keeping a single authoritative feature ledger. Otherwise proceed sequentially. **Begin now.**
