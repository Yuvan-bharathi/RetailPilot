/**
 * Minimal, safe markdown renderer for agent cards (headings, lists, tables, code spans/blocks, bold) — renders
 * React elements, never HTML strings. Enough for docs/agents/*.md; not a general markdown engine.
 */
import type { ReactNode } from "react";

function inline(text: string): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /(`[^`]+`|\*\*[^*]+\*\*)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const tok = m[0];
    out.push(
      tok.startsWith("`") ? (
        <code key={i++} className="rounded bg-neutral-bg px-1 text-[12px] break-all">
          {tok.slice(1, -1)}
        </code>
      ) : (
        <strong key={i++}>{tok.slice(2, -2)}</strong>
      ),
    );
    last = m.index + tok.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

export function MarkdownLite({ source }: { source: string }) {
  const lines = source.replaceAll("\r\n", "\n").split("\n");
  const blocks: ReactNode[] = [];
  let i = 0;
  let key = 0;
  while (i < lines.length) {
    const line = lines[i] ?? "";
    if (line.startsWith("```")) {
      const body: string[] = [];
      i += 1;
      while (i < lines.length && !(lines[i] ?? "").startsWith("```")) body.push(lines[i++] ?? "");
      i += 1;
      blocks.push(
        <pre key={key++} className="overflow-x-auto rounded-input bg-neutral-bg p-3 text-[12px]">
          {body.join("\n")}
        </pre>,
      );
      continue;
    }
    const h = /^(#{1,4})\s+(.*)$/.exec(line);
    if (h) {
      const level = h[1]!.length;
      const cls =
        level <= 1 ? "text-base font-semibold" : level === 2 ? "text-sm font-semibold" : "text-sm font-medium";
      blocks.push(
        <p key={key++} role="heading" aria-level={level + 2} className={`${cls} mt-3 text-ink`}>
          {inline(h[2]!)}
        </p>,
      );
      i += 1;
      continue;
    }
    if (/^\s*[-*]\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*[-*]\s+/.test(lines[i] ?? "")) {
        let item = (lines[i++] ?? "").replace(/^\s*[-*]\s+/, "");
        // a wrapped item continues until a blank line, a new item, a heading, a table or a code fence
        while (i < lines.length && (lines[i] ?? "").trim() !== "" && !/^(\s*[-*]\s|#|\||```)/.test(lines[i] ?? ""))
          item += " " + (lines[i++] ?? "").trim();
        items.push(item);
      }
      blocks.push(
        <ul key={key++} className="list-disc space-y-0.5 pl-5">
          {items.map((t, j) => (
            <li key={j}>{inline(t)}</li>
          ))}
        </ul>,
      );
      continue;
    }
    if (line.startsWith("|")) {
      const rows: string[][] = [];
      while (i < lines.length && (lines[i] ?? "").startsWith("|")) {
        const cells = (lines[i++] ?? "")
          .split("|")
          .slice(1, -1)
          .map((c) => c.trim());
        if (!cells.every((c) => /^:?-+:?$/.test(c))) rows.push(cells);
      }
      const [head, ...body] = rows;
      blocks.push(
        <div key={key++} className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            {head ? (
              <thead>
                <tr className="border-b border-border">
                  {head.map((c, j) => (
                    <th key={j} className="px-2 py-1 font-semibold">
                      {inline(c)}
                    </th>
                  ))}
                </tr>
              </thead>
            ) : null}
            <tbody>
              {body.map((r, j) => (
                <tr key={j} className="border-b border-divider">
                  {r.map((c, k) => (
                    <td key={k} className="px-2 py-1 align-top">
                      {inline(c)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>,
      );
      continue;
    }
    if (line.trim() === "") {
      i += 1;
      continue;
    }
    const para: string[] = [];
    while (i < lines.length && (lines[i] ?? "").trim() !== "" && !/^(#|```|\||\s*[-*]\s)/.test(lines[i] ?? ""))
      para.push(lines[i++] ?? "");
    blocks.push(
      <p key={key++} className="text-sm">
        {inline(para.join(" "))}
      </p>,
    );
  }
  return <div className="space-y-2 text-ink">{blocks}</div>;
}
