# CI consolidation

Pull requests intentionally expose one automatic GitHub Actions workflow: `.github/workflows/ci.yml`.

All Metal backend and Vitrail smoke-launcher static contracts are consolidated in `tools/ci-contracts.py`. Add new phase coverage there instead of adding another pull-request workflow.

Release publishing is isolated in `.github/workflows/release.yml`, which triggers only on `v*` tags.

The PR workflow uses `concurrency.cancel-in-progress: true`, so a newer commit cancels an older CI run for the same pull request.
