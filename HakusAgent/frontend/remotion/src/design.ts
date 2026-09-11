import tokens from '../../hakus-design-tokens.json'

export const design = tokens

export const fontFamily = design.fontFamily.display

export const surfaceStyle = {
  backgroundColor: design.color.surface,
  color: design.color.ink,
  fontFamily,
} as const
