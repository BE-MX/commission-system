export function descriptionColumns(width, maximum = 3) {
  return Math.max(1, Math.min(Math.max(1, maximum), Math.floor(width / 240)))
}
