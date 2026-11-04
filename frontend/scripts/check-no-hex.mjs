// Fails if a hex colour appears anywhere in src/ except src/styles/tokens.css (design doc §1: tokens only).
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../src", import.meta.url));
const allowed = join(root, "styles", "tokens.css");
const skip = new Set([join(root, "api", "schema.d.ts")]);
const hex = /#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})\b/g;
const extensions = /\.(tsx?|css|html)$/;

function* walk(dir) {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) yield* walk(path);
    else if (extensions.test(name)) yield path;
  }
}

const problems = [];
for (const file of walk(root)) {
  if (file === allowed || skip.has(file)) continue;
  readFileSync(file, "utf8")
    .split("\n")
    .forEach((line, i) => {
      for (const match of line.matchAll(hex)) problems.push(`${relative(root, file).split(sep).join("/")}:${i + 1}  ${match[0]}`);
    });
}

if (problems.length) {
  console.error(`Hex colours outside src/styles/tokens.css — use a design token instead:\n  ${problems.join("\n  ")}`);
  process.exit(1);
}
console.log("check:no-hex ok — colours come from tokens.css only");
