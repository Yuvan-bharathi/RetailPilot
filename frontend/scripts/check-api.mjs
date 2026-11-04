// Fails if src/api/schema.d.ts was not regenerated from openapi.json (`npm run gen:api`).
// The backend test tests/unit/test_contract.py checks the other half: openapi.json matches the FastAPI app.
import { execFileSync } from "node:child_process";
import { mkdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const frontend = join(here, "..");
const committed = join(frontend, "src", "api", "schema.d.ts");
const fresh = join(frontend, "node_modules", ".tmp", "schema.check.d.ts");
mkdirSync(dirname(fresh), { recursive: true });

const cli = join(frontend, "node_modules", "openapi-typescript", "bin", "cli.js");
execFileSync(process.execPath, [cli, join(frontend, "openapi.json"), "-o", fresh], { stdio: "ignore" });

const normalise = (text) => text.replace(/\r\n/g, "\n");
if (normalise(readFileSync(committed, "utf8")) !== normalise(readFileSync(fresh, "utf8"))) {
  console.error(
    "src/api/schema.d.ts is stale — run `npm run gen:api` (after exporting openapi.json from the backend).",
  );
  process.exit(1);
}
console.log("check:api ok — generated types match openapi.json");
