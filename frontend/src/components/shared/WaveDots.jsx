/** Three dots in a wave — the app's "working on it" mark. Inherits colour. */
export default function WaveDots({ className = '' }) {
  return (
    <span className={`u-wave ${className}`} aria-hidden="true">
      <i /><i /><i />
    </span>
  )
}
