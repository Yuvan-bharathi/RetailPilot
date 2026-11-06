/**
 * Visual flow of one run (docs/09 §3.4): hand-built SVG + positioned buttons (React Flow is not a project
 * dependency; same API shape: nodes with fixed x/y, edges source → target). Static layout, no physics.
 * Node colour = run status via semantic tokens, always with an icon and a text label; nodes are buttons, so the
 * graph is keyboard reachable. Clicking an agent node opens its run trace.
 */
import { Bot, Database, ShieldCheck, Wrench, type LucideIcon } from "lucide-react";

import { useEffect, useRef, useState } from "react";

import type { GraphEdgeDTO, GraphNodeDTO } from "../../api/types";
import { RUN_STATUS } from "../../lib/agentFormat";

const W = 160;
const H = 64;

const TONE_CLASSES: Record<string, string> = {
  success: "border-success bg-success-bg",
  warning: "border-warning bg-warning-bg",
  attention: "border-attention bg-attention-bg",
  danger: "border-danger bg-danger-bg",
  info: "border-info bg-info-bg",
  neutral: "border-border bg-neutral-bg",
};

const EDGE_STYLE: Record<GraphEdgeDTO["kind"], { cls: string; dash?: string; label: string }> = {
  DATA: { cls: "stroke-decor", label: "Data hand-off" },
  REVIEW: { cls: "stroke-info", label: "Review before inbox" },
  EXCEPTION: { cls: "stroke-attention", dash: "6 4", label: "Exceptions only" },
  APPROVAL: { cls: "stroke-brand", dash: "2 4", label: "Human approval" },
};

const TYPE_ICON: Record<GraphNodeDTO["node_type"], LucideIcon> = {
  AGENT: Bot,
  TOOL: Wrench,
  GATE: ShieldCheck,
  DATA: Database,
};

function edgePath(a: GraphNodeDTO, b: GraphNodeDTO): string {
  if (a.x === b.x) {
    // same column: vertical
    const down = b.y > a.y;
    const x = a.x + W / 2;
    const y1 = down ? a.y + H : a.y;
    const y2 = down ? b.y : b.y + H;
    return `M ${x} ${y1} L ${x} ${y2}`;
  }
  const x1 = a.x + W;
  const y1 = a.y + H / 2;
  const x2 = b.x;
  const y2 = b.y + H / 2;
  const mid = (x1 + x2) / 2;
  return `M ${x1} ${y1} C ${mid} ${y1}, ${mid} ${y2}, ${x2} ${y2}`;
}

export function AgentFlowGraph({
  nodes,
  edges,
  onSelect,
  selectedId,
}: {
  nodes: GraphNodeDTO[];
  edges: GraphEdgeDTO[];
  onSelect: (node: GraphNodeDTO) => void;
  selectedId?: string | null;
}) {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const width = Math.max(...nodes.map((n) => n.x + W)) + 20;
  const height = Math.max(...nodes.map((n) => n.y + H)) + 20;
  // fit the fixed layout to the available width (down to 75 %, then scroll) — positions stay fixed, no physics
  const box = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(1);
  useEffect(() => {
    const el = box.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(([entry]) => {
      const w = entry?.contentRect.width ?? width;
      setScale(Math.min(1, Math.max(0.75, w / width)));
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [width]);

  return (
    <div className="space-y-3">
      <div ref={box} className="relative overflow-x-auto rounded-card border border-border bg-app">
        <div style={{ width: width * scale, height: height * scale }}>
          <div className="relative origin-top-left" style={{ width, height, transform: `scale(${scale})` }}>
            <svg
              aria-hidden="true"
              className="absolute inset-0"
              width={width}
              height={height}
              viewBox={`0 0 ${width} ${height}`}
            >
              <defs>
                {(["DATA", "REVIEW", "EXCEPTION", "APPROVAL"] as const).map((k) => (
                  <marker
                    key={k}
                    id={`arrow-${k}`}
                    viewBox="0 0 10 10"
                    refX="9"
                    refY="5"
                    markerWidth="7"
                    markerHeight="7"
                    orient="auto-start-reverse"
                  >
                    <path d="M 0 0 L 10 5 L 0 10 z" className={EDGE_STYLE[k].cls.replace("stroke-", "fill-")} />
                  </marker>
                ))}
              </defs>
              {edges.map((e) => {
                const a = byId.get(e.source);
                const b = byId.get(e.target);
                if (!a || !b) return null;
                const style = EDGE_STYLE[e.kind];
                const d = edgePath(a, b);
                return (
                  <g key={`${e.source}-${e.target}`}>
                    <path
                      d={d}
                      fill="none"
                      strokeWidth={1.75}
                      strokeDasharray={style.dash}
                      className={style.cls}
                      markerEnd={`url(#arrow-${e.kind})`}
                    />
                    {e.label ? (
                      <text
                        x={(a.x + (a.x === b.x ? W / 2 : W) + b.x + (a.x === b.x ? W / 2 : 0)) / 2}
                        y={(a.y + b.y + H) / 2 - 4}
                        textAnchor="middle"
                        className="fill-ink-secondary stroke-app text-[10px]"
                        strokeWidth={4}
                        paintOrder="stroke"
                      >
                        {e.label}
                      </text>
                    ) : null}
                  </g>
                );
              })}
            </svg>
            {nodes.map((n) => {
              const status = n.status ?? "NOT_RUN";
              const s = RUN_STATUS[status] ?? RUN_STATUS.NOT_RUN;
              const Icon = TYPE_ICON[n.node_type];
              const StatusIcon = s.icon;
              const selected = n.id === selectedId;
              const gate = n.node_type === "GATE";
              return (
                <button
                  key={n.id}
                  type="button"
                  onClick={() => onSelect(n)}
                  aria-pressed={selected}
                  aria-label={`${n.label}: ${s.label}${n.detail ? `, ${n.detail}` : ""}`}
                  className={`absolute flex flex-col justify-center gap-0.5 border-2 px-2.5 text-left shadow-card transition-shadow hover:shadow-dropdown ${
                    gate ? "rounded-[28px]" : n.node_type === "AGENT" ? "rounded-card" : "rounded-input border-dashed"
                  } ${TONE_CLASSES[s.tone]} ${selected ? "ring-2 ring-brand ring-offset-2" : ""}`}
                  style={{ left: n.x, top: n.y, width: W, height: H }}
                >
                  <span className="flex items-center gap-1.5 text-xs font-semibold text-ink">
                    <Icon aria-hidden="true" size={13} className="shrink-0" />
                    <span className="truncate">{n.label}</span>
                  </span>
                  <span className="flex items-center gap-1 text-[11px] text-ink-secondary">
                    <StatusIcon aria-hidden="true" size={11} className="shrink-0" />
                    {s.label}
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      </div>
      <ul aria-label="Legend" className="flex flex-wrap gap-x-5 gap-y-1 text-xs text-ink-secondary">
        {(Object.keys(EDGE_STYLE) as GraphEdgeDTO["kind"][]).map((k) => (
          <li key={k} className="flex items-center gap-1.5">
            <svg aria-hidden="true" width="28" height="8">
              <line
                x1="0"
                y1="4"
                x2="28"
                y2="4"
                strokeWidth="2"
                strokeDasharray={EDGE_STYLE[k].dash}
                className={EDGE_STYLE[k].cls}
              />
            </svg>
            {EDGE_STYLE[k].label}
          </li>
        ))}
        <li className="flex items-center gap-1.5">
          <ShieldCheck aria-hidden="true" size={13} /> Rounded node = human approval gate
        </li>
        <li className="flex items-center gap-1.5">
          <Wrench aria-hidden="true" size={13} /> Dashed node = deterministic tool / data
        </li>
      </ul>
    </div>
  );
}
