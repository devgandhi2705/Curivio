/**
 * Onboarding step <-> URL mapping. Keeps App.jsx (URL parsing) and
 * OnboardingModal.jsx (step navigation) in sync on the same slugs.
 */

export const ONBOARDING_STEPS = ["project", "topics", "launch"]

export function onboardingStepIndex(slug) {
  const i = ONBOARDING_STEPS.indexOf(slug)
  return i === -1 ? 0 : i
}

export function onboardingStepPath(slugOrIndex) {
  const slug = typeof slugOrIndex === "number" ? ONBOARDING_STEPS[slugOrIndex] : slugOrIndex
  return `/feed/onboarding/${slug}`
}

/**
 * Parses a /feed/... pathname. Returns the onboarding step slug if this is
 * an onboarding URL (defaulting an unknown/missing step to "project"), else
 * null. Lets App.jsx tell "/feed/onboarding/..." apart from "/feed/:projectId".
 */
export function parseOnboardingStep(pathname) {
  if (!pathname.startsWith("/feed/onboarding")) return null
  const slug = pathname.slice("/feed/onboarding".length).split("/").filter(Boolean)[0]
  return ONBOARDING_STEPS.includes(slug) ? slug : "project"
}
