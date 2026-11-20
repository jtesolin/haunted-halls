"use client";

import { useMemo, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import { Minus, Plus, RotateCcw } from "lucide-react";
import { layoutGraph } from "@/lib/exploration-layout";
import type { ExplorationEdge, ExplorationNode } from "@/types/exploration";

const MIN_ZOOM = 0.4;
const MAX_ZOOM = 3;
const DRAG_THRESHOLD_PX = 4;
const ZOOM_BUTTON_CLASS =
  "inline-flex h-7 w-7 items-center justify-center rounded-md border border-white/15 bg-zinc-900/80 text-zinc-300 transition hover:bg-white/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/70";

function truncate(text: string, max: number) {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

export default function ExplorationMap({
  nodes,
  edges,
  currentRoomId,
  selectedRoomId,
  onSelectRoom,
}: {
  nodes: ExplorationNode[];
  edges: ExplorationEdge[];
  currentRoomId: string;
  selectedRoomId: string;
  onSelectRoom: (roomId: string) => void;
}) {
  const layout = useMemo(() => layoutGraph(nodes, edges, currentRoomId), [nodes, edges, currentRoomId]);
  const [view, setView] = useState({ x: 0, y: 0, k: 1 });
  const drag = useRef<{ startX: number; startY: number; originX: number; originY: number; moved: boolean } | null>(null);
  const svgRef = useRef<SVGSVGElement | null>(null);
  const { bounds } = layout;
  const cx = bounds.x + bounds.width / 2;
  const cy = bounds.y + bounds.height / 2;

  const zoomBy = (factor: number) =>
    setView((current) => ({ ...current, k: Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, current.k * factor)) }));

  const onPointerDown = (event: PointerEvent<SVGSVGElement>) => {
    drag.current = { startX: event.clientX, startY: event.clientY, originX: view.x, originY: view.y, moved: false };
  };
  const onPointerMove = (event: PointerEvent<SVGSVGElement>) => {
    const state = drag.current;
    if (!state || event.buttons === 0) {
      return;
    }
    const dx = event.clientX - state.startX;
    const dy = event.clientY - state.startY;
    if (!state.moved && Math.hypot(dx, dy) < DRAG_THRESHOLD_PX) {
      return;
    }
    state.moved = true;
    // Convert screen pixels to viewBox units so panning tracks the pointer at any rendered size.
    const rect = svgRef.current?.getBoundingClientRect();
    const scale = rect && rect.width > 0 ? Math.max(bounds.width / rect.width, bounds.height / (rect.height || 1)) : 1;
    setView((current) => ({ ...current, x: state.originX + dx * scale, y: state.originY + dy * scale }));
  };
  const endDrag = () => {
    // Keep `moved` readable by the click that follows pointerup, then clear it.
    setTimeout(() => {
      drag.current = null;
    }, 0);
  };

  const select = (roomId: string) => {
    if (!drag.current?.moved) {
      onSelectRoom(roomId);
    }
  };
  const onNodeKey = (event: KeyboardEvent<SVGGElement>, roomId: string) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onSelectRoom(roomId);
    }
  };

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs text-zinc-500">Drag to pan. Select a visited room to read its notes.</p>
        <div className="flex shrink-0 items-center gap-1" role="group" aria-label="Map zoom">
          <button type="button" aria-label="Zoom out" onClick={() => zoomBy(1 / 1.25)} className={ZOOM_BUTTON_CLASS}>
            <Minus className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
          <button type="button" aria-label="Zoom in" onClick={() => zoomBy(1.25)} className={ZOOM_BUTTON_CLASS}>
            <Plus className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
          <button
            type="button"
            aria-label="Reset map view"
            onClick={() => setView({ x: 0, y: 0, k: 1 })}
            className={ZOOM_BUTTON_CLASS}
          >
            <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
        </div>
      </div>

      <svg
        ref={svgRef}
        role="group"
        aria-label="Exploration map"
        viewBox={`${bounds.x} ${bounds.y} ${bounds.width} ${bounds.height}`}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endDrag}
        onPointerLeave={endDrag}
        onPointerCancel={endDrag}
        className="h-72 w-full cursor-grab touch-none select-none rounded-xl border border-white/10 bg-black/30 active:cursor-grabbing"
      >
        <defs>
          <marker id="exploration-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M 0 0 L 10 5 L 0 10 z" className="fill-zinc-400" />
          </marker>
        </defs>
        <g transform={`translate(${view.x} ${view.y}) translate(${cx} ${cy}) scale(${view.k}) translate(${-cx} ${-cy})`}>
          {layout.edges.map(({ edge, path, labelX, labelY }) => (
            <g key={edge.id} data-testid="map-edge">
              <title>{`${edge.label} (${edge.kind}${edge.traversed ? "" : ", not yet traversed"})`}</title>
              <path
                d={path}
                fill="none"
                markerEnd="url(#exploration-arrow)"
                strokeDasharray={edge.traversed ? undefined : "5 4"}
                className={edge.kind === "exit" ? "stroke-zinc-500" : "stroke-amber-400/80"}
                strokeWidth={1.5}
              />
              <text x={labelX} y={labelY} textAnchor="middle" className="fill-zinc-500 text-[10px]">
                {truncate(edge.label, 16)}
              </text>
            </g>
          ))}

          {layout.nodes.map(({ node, x, y, half }) => {
            if (node.kind === "frontier") {
              // Anonymous: nothing about the destination is shown and it is never selectable.
              return (
                <g key={node.id} data-testid="map-frontier">
                  <title>Unexplored</title>
                  <circle cx={x} cy={y} r={half.w} className="fill-zinc-900 stroke-zinc-600" strokeDasharray="3 3" />
                  <text x={x} y={y + 4} textAnchor="middle" className="fill-zinc-500 text-[12px]" aria-hidden="true">
                    ?
                  </text>
                </g>
              );
            }
            const name = node.name ?? "Unnamed room";
            const isCurrent = node.id === currentRoomId;
            const isSelected = node.id === selectedRoomId;
            return (
              <g
                key={node.id}
                role="button"
                tabIndex={0}
                aria-label={`${name}${isCurrent ? " (current room)" : ""}`}
                aria-pressed={isSelected}
                data-current={isCurrent}
                data-selected={isSelected}
                onClick={() => select(node.id)}
                onKeyDown={(event) => onNodeKey(event, node.id)}
                className="cursor-pointer outline-none [&:focus-visible>rect]:stroke-sky-300"
              >
                <title>{name}</title>
                <rect
                  x={x - half.w}
                  y={y - half.h}
                  width={half.w * 2}
                  height={half.h * 2}
                  rx={10}
                  className={isCurrent ? "fill-emerald-900/70 stroke-emerald-400" : "fill-zinc-800 stroke-zinc-600"}
                  strokeWidth={1.5}
                />
                {isSelected ? (
                  <rect
                    x={x - half.w - 4}
                    y={y - half.h - 4}
                    width={half.w * 2 + 8}
                    height={half.h * 2 + 8}
                    rx={13}
                    fill="none"
                    className="stroke-sky-400"
                    strokeWidth={2.5}
                  />
                ) : null}
                <text x={x} y={y + 4} textAnchor="middle" className="fill-zinc-100 text-[11px] font-semibold">
                  {truncate(name, 18)}
                </text>
                {isCurrent ? (
                  <text x={x} y={y - half.h - 8} textAnchor="middle" className="fill-emerald-300 text-[10px] font-semibold">
                    You are here
                  </text>
                ) : null}
              </g>
            );
          })}
        </g>
      </svg>

      <ul className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-zinc-400" aria-label="Map legend">
        <li className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm border border-emerald-400 bg-emerald-900/70" />Current room</li>
        <li className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm border-2 border-sky-400" />Selected room</li>
        <li className="flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-full border border-dashed border-zinc-500" />Unexplored</li>
      </ul>
    </div>
  );
}
