/**
 * Widget surface design tokens — distinct from the mobile theme.
 *
 * Aesthetic commitment: compact dev-tool / game-HUD overlay. The "Close Your
 * Loops Noob" name is playful and gamer-adjacent on purpose; the visual
 * language matches — punchy electric lime accent, dark slate background
 * (GitHub-dark-adjacent so it sits cleanly next to a code editor), JetBrains
 * Mono for the HUD header text, Sora for content. NO refined serif — that's
 * the mobile screen's job. This one is a sharp utility object.
 */

export const widgetColors = {
  // Very dark slate base — almost-black, slight blue undertone. Reads
  // as "tool window" not "content surface."
  bg: '#0d1117',
  surface: '#161b22',
  surfaceHover: '#1c2128',
  surfaceElevated: '#21262d',

  // Text
  text: '#f0f6fc',           // bright white-ish
  textDim: '#8b949e',        // muted slate
  textFaint: '#6e7681',
  textOnAccent: '#0d1117',   // for buttons with accent background

  // Single dominant accent — electric lime. Reads as "GO" / "ACTIVE".
  // Distinct from the mobile screen's terra-cotta so the two surfaces
  // feel like different tools.
  accent: '#aef359',
  accentDim: '#7fb33d',      // for hover states / muted accents
  accentBright: '#c8ff7c',   // for hover/highlight

  // Status
  done: '#7ee787',           // softer success green for completed states
  doneDim: '#56875c',

  // Borders + hairlines
  border: '#30363d',
  borderActive: '#aef359',   // active task gets a lime border

  // Subtle warning / overdue (not used yet but reserved)
  warning: '#f7b955',
} as const;

export const widgetFonts = {
  // HUD header — monospace, all caps, slight letter-spacing. Reads as
  // "dev tool window title bar."
  hud: 'JetBrainsMono_700Bold',
  hudMedium: 'JetBrainsMono_500Medium',
  // Body — geometric sans with character (not Inter/Roboto — design skill
  // explicitly steers away from generic system-ish fonts).
  body: 'Sora_400Regular',
  bodyMedium: 'Sora_600SemiBold',
  bodyBold: 'Sora_700Bold',
} as const;

export const widgetType = {
  // The HUD title bar — "CLOSE YOUR LOOPS NOOB"
  hud: {
    fontFamily: widgetFonts.hud,
    fontSize: 12,
    lineHeight: 14,
    letterSpacing: 1.6,
  },
  // Task title — bold, scannable
  taskTitle: {
    fontFamily: widgetFonts.bodyBold,
    fontSize: 15,
    lineHeight: 20,
  },
  // Task description ("why" line, est)
  taskMeta: {
    fontFamily: widgetFonts.body,
    fontSize: 12,
    lineHeight: 16,
  },
  // Duration badge — tabular numbers, mono
  duration: {
    fontFamily: widgetFonts.hudMedium,
    fontSize: 11,
    lineHeight: 14,
    letterSpacing: 0.5,
  },
  // Subtask checklist row
  subtask: {
    fontFamily: widgetFonts.body,
    fontSize: 13,
    lineHeight: 18,
  },
  // Button label
  button: {
    fontFamily: widgetFonts.bodyBold,
    fontSize: 12,
    lineHeight: 14,
    letterSpacing: 0.6,
  },
  // Date / wordmark sub-line
  micro: {
    fontFamily: widgetFonts.hudMedium,
    fontSize: 10,
    lineHeight: 12,
    letterSpacing: 1.0,
  },
} as const;

export const widgetSpacing = {
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 24,
} as const;

export const widgetRadii = {
  sm: 4,
  md: 6,
  lg: 8,
  pill: 999,
} as const;

// Max widget width — feels right at this width per the reference shot;
// looks like a real overlay panel, not a full-page app on desktop.
export const WIDGET_MAX_WIDTH = 380;
