/**
 * Lite-device detection and haptics. The app always runs full motion — no
 * in-app switch and no following the OS reduce-motion setting (user decision
 * 2026-10-02). index.html marks lite phones before first paint.
 */

export const HAPTIC_PATTERNS = { tap: 10, success: [12, 40, 18] }

/* ponytail: memory/cores is a coarse proxy for "will drop frames"; swap for a
   measured frame-time probe if lite mode ever misfires on real devices. */
export function isLiteDevice({ coarse, memory, cores }) {
  if (!coarse) return false
  return (memory != null && memory <= 4) || (cores != null && cores <= 4)
}

/** Android buzzes; iOS has no vibration API and ignores this. */
export function haptic(kind) {
  navigator.vibrate?.(HAPTIC_PATTERNS[kind] ?? 0)
}
