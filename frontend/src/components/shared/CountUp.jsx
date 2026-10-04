import { useCountUp } from '../../hooks/useCountUp.js'
import { formatCount, splitCount } from '../../lib/motionMath.js'

/** A number that counts up and lands with a small pop. Non-numbers render as-is. */
export default function CountUp({ value, className = '' }) {
  const parts = splitCount(value)
  const shown = useCountUp(parts ? parts.n : 0)
  if (!parts) return <span className={className}>{value}</span>
  return (
    <span data-countup className={`u-land ${className}`}>
      {parts.prefix}{formatCount(shown, parts)}{parts.suffix}
    </span>
  )
}
