// Outline port: the shape of a pen stroke as SVG path data, from the vendored perfect-freehand (MIT).
import { getStroke } from '../vendor/perfect-freehand.mjs';

/** points are [x, y, pressure]; width is the line's diameter in CSS px at pressure 0.5. */
export function outline(points, width) {
  // The saved pressure is real or the 0.5 default, so the library must not guess a pressure from the speed.
  const shape = getStroke(points, { size: width, thinning: 0.5, smoothing: 0.5, streamline: 0.5, simulatePressure: false });
  if (!shape.length) return '';
  // Midpoints as the quadratic curve's end points make the outline smooth instead of a polygon.
  const path = shape.reduce((acc, [x0, y0], i, all) => {
    const [x1, y1] = all[(i + 1) % all.length];
    acc.push(x0, y0, (x0 + x1) / 2, (y0 + y1) / 2);
    return acc;
  }, ['M', ...shape[0], 'Q']);
  return path.join(' ') + ' Z';
}
