import { useMemo } from 'react'

/* ═════════════════════════════════════════════════════════════════════════
   THE WIRE PLATE — a seeded constellation of nodes wired to their nearest
   neighbours. Extracted from LandingPage so the auth screen can carry the
   same figure without importing the whole landing component; the emitted
   class names are unchanged, so landing.css still styles the landing's
   plates exactly as before.

   Geometry is a pure function of `seed`, so a plate is identical on every
   render and never reshuffles.

   AMBIENT throughout — the field drifts, nodes twinkle on their own offsets,
   and edges draw and retract. Nothing here is scroll-triggered.
   ═════════════════════════════════════════════════════════════════════════ */

const PLATE_W = 400
const PLATE_H = 300

/* mulberry32 — small, fast, and identical for a given seed on every render */
function rng(seed) {
  let a = seed >>> 0
  return () => {
    a = (a + 0x6D2B79F5) >>> 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

function buildPlate(seed, count) {
  const rand = rng(seed)
  const pts = []
  /* rejection sampling: 600 tries is plenty to place ~26 points at a 38px
     minimum separation in a 400x300 box, and bounding the loop means a bad
     seed can never spin */
  for (let i = 0; i < 600 && pts.length < count; i++) {
    const x = 14 + rand() * (PLATE_W - 28)
    const y = 14 + rand() * (PLATE_H - 28)
    if (pts.every(p => Math.hypot(p.x - x, p.y - y) >= 38)) {
      pts.push({ x, y, r: 1.1 + rand() * 2.7, d: rand() * 7, t: 5 + rand() * 5 })
    }
  }
  /* wire each node to its two nearest neighbours, deduped — a nearest-neighbour
     graph reads as a structure; random pairs read as scribble */
  const seen = new Set()
  const edges = []
  pts.forEach((p, i) => {
    const near = pts
      .map((q, j) => ({ j, d: Math.hypot(p.x - q.x, p.y - q.y) }))
      .filter(o => o.j !== i)
      .sort((a, b) => a.d - b.d)
      .slice(0, 2)
    for (const { j, d } of near) {
      if (d > 104) continue
      const key = i < j ? `${i}:${j}` : `${j}:${i}`
      if (seen.has(key)) continue
      seen.add(key)
      edges.push({ a: p, b: pts[j], d: rand() * 9 })
    }
  })
  return { pts, edges }
}

/* `rings` adds two slow concentric arcs — reserved for the largest plate, so
   the biggest void reads as a deliberate figure rather than more of the same */
export default function Plate({ seed = 1, count = 26, rings = false, className = "" }) {
  const { pts, edges } = useMemo(() => buildPlate(seed, count), [seed, count])
  return (
    <svg className={`lp-plate ${className}`} viewBox={`0 0 ${PLATE_W} ${PLATE_H}`}
         fill="none" aria-hidden="true" focusable="false">
      {rings && (
        <g className="lp-plate-rings">
          <circle cx="248" cy="150" r="96" pathLength="1" />
          <circle cx="248" cy="150" r="140" pathLength="1" style={{ "--d": "1.4s" }} />
        </g>
      )}
      {edges.map((e, i) => (
        <path key={i} className="lp-plate-edge" pathLength="1"
              d={`M${e.a.x.toFixed(1)} ${e.a.y.toFixed(1)}L${e.b.x.toFixed(1)} ${e.b.y.toFixed(1)}`}
              style={{ "--d": `${e.d.toFixed(2)}s` }} />
      ))}
      {pts.map((p, i) => (
        <circle key={i} className="lp-plate-node"
                cx={p.x.toFixed(1)} cy={p.y.toFixed(1)} r={p.r.toFixed(2)}
                style={{ "--d": `${p.d.toFixed(2)}s`, "--t": `${p.t.toFixed(2)}s` }} />
      ))}
    </svg>
  )
}
