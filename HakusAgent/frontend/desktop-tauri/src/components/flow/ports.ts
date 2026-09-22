/**
 * Port geometry — where handles and their labels sit on a node card.
 *
 * The formula used to be written out at four call sites; a node with more than
 * three ports on one side pushed the labels past 100% and off the card. Ports
 * are now distributed evenly down the card, and the label is only rendered when
 * the direction is genuinely ambiguous.
 */

/** Vertical position (as a CSS percentage) of port `index` of `total`. */
export function portTop(index: number, total: number): string {
  if (total <= 1) return '50%'
  // Keep the first and last port inset from the card edges so labels stay
  // legible at any zoom, rather than hugging 0%/100%.
  const span = 62
  const start = 50 - span / 2
  return `${start + (span * index) / (total - 1)}%`
}

/** Port labels are noise on a plain one-in-one-out node. */
export function shouldShowPortLabels(inputs: number, outputs: number): boolean {
  return inputs > 1 || outputs > 1
}
