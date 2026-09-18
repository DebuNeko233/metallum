# CI consolidation

Pull requests intentionally expose one automatic GitHub Actions workflow: `.github/workflows/ci.yml`.

All Metal backend and Vitrail smoke-launcher static contracts live in the `tools/ci-*.py` scripts that `ci.yml` names one by one; `tools/ci-contracts.py` is the largest of them. Add new phase coverage to one of those scripts instead of adding another pull-request workflow. `ci-contracts.py` fails when a `tools/ci-*.py` script is named by no workflow, so a contract cannot sit in the tree looking like coverage while nothing runs it.

Release publishing is isolated in `.github/workflows/release.yml`, which triggers only on `v*` tags.

The PR workflow uses `concurrency.cancel-in-progress: true`, so a newer commit cancels an older CI run for the same pull request.

`tools/ci-contracts.py` enforces that shape instead of trusting it: a workflow that could author a commit is refused, `contents: write` is reserved for `release.yml`, every workflow must state its `permissions:` explicitly, and a second `pull_request` workflow fails CI. The guard reads each workflow's declared permissions rather than matching the text `contents: write`, because `permissions: write-all`, a quoted value and a trailing comment all grant the same token. A workflow that commits to a branch is not a helper; it is an author nobody reviewed, which is what `apply-graphics-storage-image-fix.yml` became before it was deleted.
