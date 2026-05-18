# Python local test and deploy workflow

This repository is a Python stock analysis dashboard. The agent workflow should optimize for local Python testing, data schema safety, and clean server deployment.

## Local validation stages

1. Create and activate a virtual environment (`python -m venv venv` then `source venv/bin/activate`).
2. Install Python dependencies inside that virtual environment with `pip install -r requirements.txt`.
3. Run formatting or lint checks when configured.
4. Run the test suite with `pytest` locally.
5. Validate recommendation schema fixtures when changed.
6. Build a deployment artifact containing only runtime files.
7. Save local command output for debugging and repair loops.

## CI usage

CI is optional for this repository and should be treated as a secondary verification layer, not the primary development loop. For day-to-day iteration, run checks locally first.

Always install requirements through the project virtual environment. Do not rely on globally installed Python packages.

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

1. Local validation passes on the branch.
2. Build a clean artifact directory.
3. Sync artifact to a release directory on the server.
4. Install dependencies in the server virtualenv.
5. Swap the current symlink to the new release.
6. Restart the service.
7. Run a health check.
8. If health check fails, roll back to the previous release.

## Agent repair loop

When local validation, CI (if used), or deploy fails, collect only the relevant command, traceback, failing test, and changed files. Give that context back to Cline with the repair prompt. The agent should make the smallest possible fix and rerun the failed command first.
