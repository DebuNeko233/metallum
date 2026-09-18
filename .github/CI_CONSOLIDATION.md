# CI consolidation

Pull requests intentionally expose one automatic GitHub Actions workflow: `.github/workflows/ci.yml`.

All Metal backend and Vitrail smoke-launcher static contracts are consolidated in `tools/ci-contracts.py`. Add new phase coverage there instead of adding another pull-request workflow.

Release publishing is isolated in `.github/workflows/release.yml`, which triggers only on `v*` tags.

The PR workflow uses `concurrency.cancel-in-progress: true`, so a newer commit cancels an older CI run for the same pull request.

`tools/ci-contracts.py` enforces both halves of that shape instead of trusting them: a workflow that could author a commit is refused, `contents: write` is reserved for `release.yml`, every workflow must state its `permissions:` explicitly, and a second `pull_request` workflow fails CI. A workflow that commits to a branch is not a helper; it is an author nobody reviewed, which is what `apply-graphics-storage-image-fix.yml` became before it was deleted.
