"use client";

import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import { LocateFixed, Maximize2, Minus, Plus } from "lucide-react";
import { layoutGraph } from "@/lib/exploration-layout";
import type { ExplorationEdge, ExplorationNode } from "@/types/exploration";

const MIN_ZOOM = 0.25;
const MAX_ZOOM = 3;
const DRAG_THRESHOLD_PX = 4;
const FALLBACK_SIZE = { width: 320, height: 288 };
const ZOOM_BUTTON_CLASS =
  "inline-flex h-7 w-7 items-center justify-center rounded-md border border-white/15 bg-zinc-900/80 text-zinc-300 transition hover:bg-white/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/70";
const clamp = (value: number, min: number, max: number) => Math.min(max, Math.max(min, value));

function truncate(text: string, max: number) {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

type View = { cx: number; cy: number; k: number };

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
  const { bounds } = layout;
  const nameOf = (id: string) => nodes.find((n) => n.id === id)?.name ?? "Unnamed room";
  const currentSpot = layout.nodes.find((entry) => entry.node.id === currentRoomId);
  const homeView = useMemo<View>(() => ({ cx: currentSpot?.x ?? 0, cy: currentSpot?.y ?? 0, k: 1 }), [currentSpot?.x, currentSpot?.y]);

  const svgRef = useRef<SVGSVGElement | null>(null);
  const [size, setSize] = useState(FALLBACK_SIZE);
  // At zoom 1 one map unit is one CSS pixel, so labels stay readable however large the graph is.
  const [view, setView] = useState<View>(homeView);
  const drag = useRef<{ startX: number; startY: number; origin: View; moved: boolean } | null>(null);
  const pointers = useRef(new Map<number, { x: number; y: number }>());
  const pinch = useRef<{ distance: number; k: number } | null>(null);

  useEffect(() => {
    const el = svgRef.current;
    if (!el || typeof ResizeObserver === "undefined") {
      return;
    }
    const observer = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      if (width > 0 && height > 0) {
        setSize({ width, height });
      }
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  // A new current room re-homes the view (the layout is re-rooted there), even after the user panned.
  const [lastRoomId, setLastRoomId] = useState(currentRoomId);
  if (lastRoomId !== currentRoomId) {
    setLastRoomId(currentRoomId);
    setView(homeView);
  }

  const limit = (next: View): View => ({
    k: clamp(next.k, MIN_ZOOM, MAX_ZOOM),
    cx: clamp(next.cx, bounds.x, bounds.x + bounds.width),
    cy: clamp(next.cy, bounds.y, bounds.y + bounds.height),
  });
  const change = (next: View) => {
    setView(limit(next));
  };
  const zoomBy = (factor: number) => change({ ...shown, k: shown.k * factor });
  const reset = () => {
    setView(homeView);
  };
  const fitAll = () => {
    setView(
      limit({
        cx: bounds.x + bounds.width / 2,
        cy: bounds.y + bounds.height / 2,
        k: Math.min(size.width / bounds.width, size.height / bounds.height),
      })
    );
  };

  // Clamped on every render so a refresh that shrinks the bounds cannot strand the view.
  const shown = limit(view);
  const viewW = size.width / shown.k;
  const viewH = size.height / shown.k;
  const viewBox = `${shown.cx - viewW / 2} ${shown.cy - viewH / 2} ${viewW} ${viewH}`;

  const onPointerDown = (event: PointerEvent<SVGSVGElement>) => {
    if (event.pointerType === "mouse" && event.button !== 0) {
      return;
    }
    pointers.current.set(event.pointerId, { x: event.clientX, y: event.clientY });
    if (pointers.current.size === 2) {
      const [a, b] = [...pointers.current.values()];
      pinch.current = { distance: Math.hypot(a.x - b.x, a.y - b.y) || 1, k: shown.k };
      drag.current = { startX: 0, startY: 0, origin: shown, moved: true };
      return;
    }
    drag.current = { startX: event.clientX, startY: event.clientY, origin: shown, moved: false };
  };
  const onPointerMove = (event: PointerEvent<SVGSVGElement>) => {
    if (!pointers.current.has(event.pointerId)) {
      return;
    }
    if (event.pointerType === "mouse" && event.buttons === 0) {
      // Button released somewhere we never saw it: stop panning.
      pointers.current.clear();
      pinch.current = null;
      drag.current = null;
      return;
    }
    pointers.current.set(event.pointerId, { x: event.clientX, y: event.clientY });
    if (pinch.current && pointers.current.size === 2) {
      const [a, b] = [...pointers.current.values()];
      change({ ...shown, k: pinch.current.k * (Math.hypot(a.x - b.x, a.y - b.y) / pinch.current.distance) });
      return;
    }
    const state = drag.current;
    if (!state) {
      return;
    }
    const dx = event.clientX - state.startX;
    const dy = event.clientY - state.startY;
    if (!state.moved && Math.hypot(dx, dy) < DRAG_THRESHOLD_PX) {
      return;
    }
    if (!state.moved) {
      // Capture only once it is a real drag so a plain click still reaches the room node.
      try {
        event.currentTarget.setPointerCapture(event.pointerId);
      } catch {
        // Capture is best-effort; the buttons check above covers a missed release.
      }
    }
    state.moved = true;
    change({ ...state.origin, cx: state.origin.cx - dx / state.origin.k, cy: state.origin.cy - dy / state.origin.k });
  };
  const endPointer = (event: PointerEvent<SVGSVGElement>) => {
    pointers.current.delete(event.pointerId);
    pinch.current = null;
    const remaining = [...pointers.current.values()];
    if (remaining.length === 1) {
      // Pinch ended with one finger still down: continue as a pan from where it is now.
      drag.current = { startX: remaining[0].x, startY: remaining[0].y, origin: shown, moved: true };
    }
    // Keep `moved` readable by the click that follows pointerup, then clear it.
    setTimeout(() => {
      if (pointers.current.size === 0) {
        drag.current = null;
      }
    }, 0);
  };
  // Plain wheel keeps scrolling the drawer; ctrl/meta+wheel (and trackpad pinch) zooms the map.
  const { x: bx, y: by, width: bw, height: bh } = bounds;
  useEffect(() => {
    const el = svgRef.current;
    if (!el) {
      return;
    }
    const handler = (event: WheelEvent) => {
      if (!event.ctrlKey && !event.metaKey) {
        return;
      }
      event.preventDefault();
      const factor = event.deltaY < 0 ? 1.15 : 1 / 1.15;
      setView((current) => ({
        ...current,
        k: clamp(current.k * factor, MIN_ZOOM, MAX_ZOOM),
        cx: clamp(current.cx, bx, bx + bw),
        cy: clamp(current.cy, by, by + bh),
      }));
    };
    el.addEventListener("wheel", handler, { passive: false });
    return () => el.removeEventListener("wheel", handler);
  }, [bx, by, bw, bh]);

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
  // Keyboard focus on a node outside the visible window brings it into view.
  const revealNode = (x: number, y: number) => {
    const margin = 70;
    const inside =
      Math.abs(x - shown.cx) < viewW / 2 - margin && Math.abs(y - shown.cy) < viewH / 2 - margin;
    if (!inside) {
      change({ ...shown, cx: x, cy: y });
    }
  };

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs text-zinc-500">Drag to pan, pinch or use the buttons to zoom. Select a visited room to read its notes.</p>
        <div className="flex shrink-0 items-center gap-1" role="group" aria-label="Map zoom">
          <button type="button" aria-label="Zoom out" onClick={() => zoomBy(1 / 1.25)} className={ZOOM_BUTTON_CLASS}>
            <Minus className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
          <button type="button" aria-label="Zoom in" onClick={() => zoomBy(1.25)} className={ZOOM_BUTTON_CLASS}>
            <Plus className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
          <button type="button" aria-label="Fit whole map" onClick={fitAll} className={ZOOM_BUTTON_CLASS}>
            <Maximize2 className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
          <button type="button" aria-label="Center on current room" onClick={reset} className={ZOOM_BUTTON_CLASS}>
            <LocateFixed className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
        </div>
      </div>

      <svg
        ref={svgRef}
        role="group"
        aria-label="Exploration map"
        viewBox={viewBox}
        data-view-scale={shown.k}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endPointer}
        onPointerCancel={endPointer}
        onLostPointerCapture={(event) => {
          // Re-targeting capture from a node to the svg fires this on the node and bubbles here;
          // only the svg losing its own capture ends the gesture.
          if (event.target === event.currentTarget) {
            endPointer(event);
          }
        }}
        className="h-72 w-full cursor-grab touch-none select-none rounded-xl border border-white/10 bg-black/30 active:cursor-grabbing"
      >
        <defs>
          <marker id="exploration-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M 0 0 L 10 5 L 0 10 z" className="fill-zinc-400" />
          </marker>
        </defs>
        <g>
          {layout.edges.map(({ edge, reverse, path, labelX, labelY }) => {
            const traversed = edge.traversed || (reverse?.traversed ?? false);
            return (
            <g key={edge.id} data-testid="map-edge" data-two-way={reverse !== null}>
              <title>
                {reverse
                  ? `${nameOf(edge.source)}: ${edge.label}; ${nameOf(reverse.source)}: ${reverse.label} (${edge.kind}${traversed ? "" : ", not yet traversed"})`
                  : `${edge.label} (${edge.kind}${edge.traversed ? "" : ", not yet traversed"})`}
              </title>
              <path
                d={path}
                fill="none"
                markerEnd={reverse ? undefined : "url(#exploration-arrow)"}
                strokeDasharray={traversed ? undefined : "5 4"}
                className={edge.kind === "exit" ? "stroke-zinc-500" : "stroke-amber-400/80"}
                strokeWidth={1.5}
              />
              <text x={labelX} y={labelY} textAnchor="middle" className="fill-zinc-500 text-[10px]">
                {truncate(edge.label, 16)}
              </text>
            </g>
            );
          })}

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
                onFocus={(event) => {
                  // Only keyboard focus scrolls the map; a mouse click must not shift it under the cursor.
                  let keyboard = true;
                  try {
                    keyboard = event.currentTarget.matches(":focus-visible");
                  } catch {
                    // Browsers without :focus-visible: treat as keyboard.
                  }
                  if (keyboard) {
                    revealNode(x, y);
                  }
                }}
                className="group cursor-pointer outline-none"
              >
                <rect
                  x={x - half.w - 9}
                  y={y - half.h - 9}
                  width={half.w * 2 + 18}
                  height={half.h * 2 + 18}
                  rx={16}
                  fill="none"
                  strokeDasharray="4 3"
                  strokeWidth={2}
                  className="stroke-transparent group-focus-visible:stroke-amber-300"
                />
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
