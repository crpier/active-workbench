import { readFileSync, readdirSync, statSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const root = new URL("../src/client", import.meta.url).pathname;

const walk = (dir) => {
  const entries = readdirSync(dir);
  for (const entry of entries) {
    const path = join(dir, entry);
    const stat = statSync(path);
    if (stat.isDirectory()) {
      walk(path);
      continue;
    }
    if (!path.endsWith(".ts")) {
      continue;
    }

    const content = readFileSync(path, "utf8");
    if (content.startsWith("// @ts-nocheck\n")) {
      continue;
    }
    writeFileSync(path, `// @ts-nocheck\n${content}`, "utf8");
  }
};

walk(root);
console.log("Applied // @ts-nocheck to generated client files");
