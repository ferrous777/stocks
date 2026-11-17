import { defineRailway, github, image, project, service, volume } from "railway/iac";

// Variables are unmanaged here (secrets are set with `railway variable set --stdin`, never in source).
// See docs/railway_deployment.md for the variables each service expects.

// MongoDB runs as a single-node replica set: the ledger needs multi-document transactions,
// which standalone mongod does not support. The background loop initiates the set once the
// root user can log in; it is idempotent (rs.status() succeeds once initiated).
const MONGO_START = [
  "sh -c '",
  // Refuse to start (before touching /data/db) until all secrets are set; otherwise the image
  // could initialize the volume without a root user.
  'if [ -z "$MONGO_KEYFILE" ] || [ -z "$MONGO_INITDB_ROOT_USERNAME" ] || [ -z "$MONGO_INITDB_ROOT_PASSWORD" ]; then ',
  'echo "missing MONGO_KEYFILE / MONGO_INITDB_ROOT_USERNAME / MONGO_INITDB_ROOT_PASSWORD" >&2; exit 1; fi; ',
  'printf %s "$MONGO_KEYFILE" > /tmp/mongo-keyfile && chmod 400 /tmp/mongo-keyfile && chown 999:999 /tmp/mongo-keyfile && ',
  "(until mongosh --quiet --host 127.0.0.1 -u \"$MONGO_INITDB_ROOT_USERNAME\" -p \"$MONGO_INITDB_ROOT_PASSWORD\" ",
  "--authenticationDatabase admin --eval ",
  "\"try { rs.status().ok } catch (e) { rs.initiate({_id: \\\"rs0\\\", members: [{_id: 0, host: \\\"$RAILWAY_PRIVATE_DOMAIN:27017\\\"}]}).ok }\" ",
  "2>/dev/null | grep -qx 1; do sleep 3; done; echo replica-set-ready) & ",
  "exec docker-entrypoint.sh mongod --replSet rs0 --keyFile /tmp/mongo-keyfile --bind_ip_all --ipv6",
  "'",
].join("");

export default defineRailway(() => {
  // Region/size as provisioned by Railway; leaving them unset makes `config plan` report a destructive change.
  const mongoData = volume("mongo-data", { region: "sfo", sizeMB: 5000 });

  const mongo = service("mongo", {
    source: image("mongo:8.0"),
    startCommand: MONGO_START,
    volumeMounts: { "/data/db": mongoData },
    replicas: { "sfo": 1 },
  });

  // Serves the JSON API (/api/v1), the website and the MCP endpoint (/mcp) from one app.
  const stocks = service("stocks", {
    source: github("ferrous777/stocks", { branch: "main", upstreamUrl: "https://github.com/ferrous777/stocks" }),
    build: { builder: "DOCKERFILE", dockerfilePath: "Dockerfile" },
    deploy: {
      healthcheckPath: "/health",
      healthcheckTimeout: 60,
      restartPolicyType: "ON_FAILURE",
      restartPolicyMaxRetries: 5,
    },
    replicas: { "sfo": 1 },
  });

  return project("heroic-adventure", {
    variables: { managed: false },
    resources: [mongoData, mongo, stocks],
  });
});
