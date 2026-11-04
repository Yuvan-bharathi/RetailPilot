// Colour rules (design doc §1, v1.1):
//  1. no hex colour anywhere in src/ except src/styles/tokens.css — use a design token;
//  2. --text-muted is NOT a text colour (fails WCAG AA, decision D-33) — decorative use only (border-decor, fill-decor …).
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../src", import.meta.url));
const allowed = join(root, "styles", "tokens.css");
const skip = new Set([join(root, "api", "schema.d.ts")]);
const hex = /#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})\b/g;
const mutedText = /(?<![-\w])text-(?:ink-)?(?:muted|decor)\b|color:\s*var\(--text-muted\)/g;
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
      const where = `${relative(root, file).split(sep).join("/")}:${i + 1}`;
      for (const match of line.matchAll(hex)) problems.push(`${where}  ${match[0]} (hex colour — use a token)`);
      for (const match of line.matchAll(mutedText))
        problems.push(`${where}  ${match[0]} (--text-muted is not a text colour, D-33)`);
    });
}

if (problems.length) {
  console.error(`Colour rule violations:\n  ${problems.join("\n  ")}`);
  process.exit(1);
}
console.log("check:no-hex ok — colours come from tokens.css only; --text-muted not used for text");
