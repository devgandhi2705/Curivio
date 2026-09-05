/**
 * The Curivio mark — an open book with a spark rising off its spine.
 *
 * Drawn, not photographed. The mark used to be a raster tile: a deep blue-black
 * rounded square with the book painted across it in a cool-to-warm gradient.
 * That gradient only ever resolved against the dark square, so the tile could
 * not be removed and the mark could not follow the theme — on paper it stayed
 * a black chip, and every surface that carried it needed its own shadow or
 * hairline ring to stop it punching a hole in the page.
 *
 * As geometry it takes `currentColor`, so it is ink on paper and cream on
 * charcoal with nothing to keep in sync: set `color` on the parent, or let it
 * inherit, and the mark is already correct in every mode. Nothing here paints
 * a background.
 *
 * Simplified for its real size. The mark is used at 24-52px, where the
 * original's page layers, edge highlights and inner glow are all sub-pixel;
 * what survives at 24px is the silhouette — two fanned pages, the gap between
 * them, and the star — so that is what is drawn.
 */
export default function LogoMark({ size = 28, className = "", style }) {
  return (
    <svg
      viewBox="0 0 32 32"
      width={size}
      height={size}
      className={`u-logo select-none ${className}`}
      style={{ width: size, height: size, ...style }}
      fill="none"
      /* decorative at every call site — a wordmark or an <h1> carries the name
         right beside it, so announcing it again would only repeat "Curivio" */
      aria-hidden="true"
      focusable="false"
    >
      {/* Left leaf. The gap between the two shapes is the spine, and it is
          2.8 units wide rather than the 1.8 the first pass used: at 24px a
          narrower one closed up and the whole mark read as a solid blob. */}
      <path
        fill="currentColor"
        d="M14.6 18.1C11.6 16.1 7.5 15 3.1 14.8c-.6 0-1.1.4-1.1 1v9.4c0 .6.5 1 1.1 1 4.1.2 7.9 1.2 10.7 2.9.4.2.8 0 .8-.4z"
      />
      {/* right leaf, mirrored on x = 16 */}
      <path
        fill="currentColor"
        d="M17.4 18.1c3-2 7.1-3.1 11.5-3.3.6 0 1.1.4 1.1 1v9.4c0 .6-.5 1-1.1 1-4.1.2-7.9 1.2-10.7 2.9-.4.2-.8 0-.8-.4z"
      />
      {/* the stem, leaving the spine and leaning into the star */}
      <path
        stroke="currentColor"
        strokeWidth="1.9"
        strokeLinecap="round"
        d="M16 17.2c0-3.3 1-5.9 3-7.8"
      />
      {/* The spark — a four-point star with concave sides, so it reads as
          light rather than as a diamond. Sits nearer the spine than the
          original's does: further right it touched the top of the right leaf
          and the two merged into one shape at nav size. */}
      <path
        fill="currentColor"
        d="M20 2.6c0 2.4 1.4 3.7 2.8 4.5-1.4.8-2.8 2.1-2.8 4.5 0-2.4-1.4-3.7-2.8-4.5 1.4-.8 2.8-2.1 2.8-4.5"
      />
    </svg>
  )
}
