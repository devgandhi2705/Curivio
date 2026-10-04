// dx, dy (px) and spin (deg) per piece — fixed, so every burst looks deliberate.
const PIECES = [
  [-40, -34, -160], [-14, -48, 120], [16, -42, 200], [34, -22, -90], [-56, -12, 80],
  [26, -58, -220], [-30, -60, 260], [4, -30, -40], [48, -40, 150], [-48, -46, -120],
]

/** CSS-only burst. Mount it (or change its key) to play; motion.css hides it
 *  under Reduced and on lite phones. */
export default function Confetti({ fire, className = '' }) {
  if (!fire) return null
  return (
    <span className={`u-confetti ${className}`} aria-hidden="true">
      {PIECES.map(([dx, dy, r], i) => (
        <i key={i} style={{ '--dx': `${dx}px`, '--dy': `${dy}px`, '--r': `${r}deg` }} />
      ))}
    </span>
  )
}
