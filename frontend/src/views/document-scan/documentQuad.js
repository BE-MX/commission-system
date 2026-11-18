export const fullFrame = () => [[0, 0], [1, 0], [1, 1], [0, 1]]

export const cross = ([ax, ay], [bx, by], [cx, cy]) => (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
export const distance = ([x1, y1], [x2, y2]) => Math.hypot(x2 - x1, y2 - y1)

export function area(points) {
  return points.reduce((sum, [x, y], index) => {
    const [nextX, nextY] = points[(index + 1) % points.length]
    return sum + x * nextY - nextX * y
  }, 0) / 2
}

export function isValidQuad(points) {
  return points.length === 4 && area(points) >= 0.008 && points.every(([x, y], i) => (
    x >= 0 && x <= 1 && y >= 0 && y <= 1
    && distance(points[i], points[(i + 1) % 4]) >= 0.025
    && cross(points[i], points[(i + 1) % 4], points[(i + 2) % 4]) > 0.0005
  ))
}

// Leave a small safety margin on automatic crops for print close to the edge.
export function padDetectedQuad(points) {
  const padding = 0.04
  const padded = points.map((point, i) => {
    const previous = points[(i + 3) % 4]
    const next = points[(i + 1) % 4]
    return point.map((value, axis) => {
      const expanded = value + (2 * value - previous[axis] - next[axis]) * padding
      return Math.min(1, Math.max(0, expanded))
    })
  })
  return isValidQuad(padded) ? padded : points
}

export function squareToQuad([[ax, ay], [bx, by], [cx, cy], [dx, dy]]) {
  // Homography taking a unit square to the four source corners.
  const sx = ax - bx + cx - dx
  const sy = ay - by + cy - dy
  const x1 = bx - cx
  const y1 = by - cy
  const x2 = dx - cx
  const y2 = dy - cy
  const determinant = x1 * y2 - x2 * y1
  const g = (sx * y2 - x2 * sy) / determinant
  const h = (x1 * sy - sx * y1) / determinant
  return [bx - ax + g * bx, dx - ax + h * dx, ax, by - ay + g * by, dy - ay + h * dy, ay, g, h]
}
