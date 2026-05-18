/**
 * Cadence design tokens. One source of truth for color, type scale, spacing.
 *
 * Aesthetic commitment: refined minimalism with intentional warmth. Cadence is
 * a daily companion for people with task-initiation friction — the surface
 * must feel calm and decisive, not busy or guilt-inducing. Single bold focal
 * point (the next task), warm dark palette, distinctive serif on the action
 * itself paired with a refined sans for everything else.
 */

export const colors = {
  // Warm dark base — slightly brown undertone, not flat black.
  bg: '#1a1814',
  surface: '#252220',
  surfaceElevated: '#2f2a25',

  // Warm off-white text, never pure white.
  text: '#f5f1ea',
  textDim: '#8a847a',
  textFaint: '#5c5750',

  // Single dominant accent — terra cotta. Used for the Start action and the
  // active timer. Never for incidental decoration.
  accent: '#e76f51',
  accentDeep: '#c5573a',

  // Success / done — sage. Quiet, satisfying.
  sage: '#88a86d',

  // Hairlines, dividers — almost invisible.
  hairline: '#3a342e',
} as const;

export const fonts = {
  // Display — distinctive warm serif. Used ONLY on the next-action title.
  display: 'Fraunces_500Medium',
  displayBold: 'Fraunces_700Bold',
  // Body — refined sans. Used for everything else.
  body: 'DMSans_400Regular',
  bodyMedium: 'DMSans_500Medium',
  bodyBold: 'DMSans_700Bold',
} as const;

// Type scale — opinionated, generous. The next-action title is the visual peak.
export const type = {
  // The one big thing.
  display: { fontFamily: fonts.display, fontSize: 34, lineHeight: 42 },
  // Section labels, button text.
  body: { fontFamily: fonts.bodyMedium, fontSize: 15, lineHeight: 22 },
  // The "why" line and up-next previews.
  caption: { fontFamily: fonts.body, fontSize: 13, lineHeight: 20 },
  // Wordmark, micro labels.
  micro: { fontFamily: fonts.bodyMedium, fontSize: 11, lineHeight: 16, letterSpacing: 1.2 },
  // The timer numbers — tabular, big.
  timer: { fontFamily: fonts.bodyBold, fontSize: 56, lineHeight: 64, letterSpacing: -1.5 },
} as const;

export const spacing = {
  xs: 4,
  sm: 8,
  md: 16,
  lg: 24,
  xl: 40,
  xxl: 64,
} as const;

export const radii = {
  sm: 6,
  md: 12,
  lg: 20,
  pill: 999,
} as const;
