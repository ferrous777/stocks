# Python CI and deploy workflow

This repository is a Python stock analysis dashboard. The agent workflow should optimize for Python tests, data schema safety, and clean server deployment.

## CI stages

1. Install Python dependencies from `requirements.txt`.
2. Run formatting or lint checks when configured.
3. Run the test suite with `pytest`.
4. Validate recommendation schema fixtures when changed.
5. Build a deployment artifact containing only runtime files.
6. Publish CI logs and artifact metadata for agent repair.

## Deploy goal

Deployment should not copy the whole working tree to the server. It should build a clean artifact and sync only files needed to run the app.

Exclude development-only files such as:

- `.git/`
- virtual environments
- local caches
- pytest caches
- editor files
- raw notebooks unless explicitly needed
- generated test output
- temporary connector files

Keep runtime files such as:

- Python packages and modules
- Flask app entry points
- templates and static assets
- config examples
- migrations or schema files
- scheduler hooks
- deployment scripts
- requirements files

## Safe deployment loop

1. CI passes on the branch.
2. Build a clean artifact directory.
3. Sync artifact to a release directory on the server.
4. Install dependencies in the server virtualenv.
5. Swap the current symlink to the new release.
6. Restart the service.
7. Run a health check.
8. If health check fails, roll back to the previous release.

## Agent repair loop

When CI or deploy fails, collect only the relevant command, traceback, failing test, and changed files. Give that context back to Cline with the repair prompt. The agent should make the smallest possible fix and rerun the failed command first.
