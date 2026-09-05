/**
 * The Curivio mark.
 *
 * The asset is a fixed-colour tile — a deep blue-black square carrying the
 * book and star — so it is never tinted per theme. What varies is how it meets
 * the ground it sits on, and that lives on `.u-logo` in theme.css: a shadow on
 * paper, a hairline ring on charcoal.
 *
 * The tile's rounded corners are baked into the asset's alpha at 23.2% of its
 * width. The radius below matches that ratio so the ring and shadow follow the
 * same curve at every size, instead of cutting across it.
 */
export default function LogoMark({ size = 28, className = "", style }) {
  return (
    <img
      src="/logo.webp"
      alt=""
      width={size}
      height={size}
      draggable="false"
      className={`u-logo select-none ${className}`}
      style={{ width: size, height: size, borderRadius: Math.round(size * 0.232), ...style }}
    />
  )
}
