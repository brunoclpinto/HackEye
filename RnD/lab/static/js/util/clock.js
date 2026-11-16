// Quarter-hour clock helpers shared with the Python side (fixture tests/fixtures/clock_cases.json).
/** Quarter-hour clock index / spoken text, same rules as collision.py clock_quarter / clock_text (bearing 0 = 12, + = right). */
export function clockQuarter(bearing) {
  const v = bearing / 7.5, q = Math.floor(Math.abs(v) + 0.5) * (v < 0 ? -1 : 1);
  return Math.max(-12, Math.min(12, q));
}
export function clockText(q) {
  const m = (720 + 15 * q) % 720, hour = Math.floor(m / 60) || 12, min = m % 60;
  return min === 0 ? `${hour}` : `${hour}:${String(min).padStart(2, "0")}`;
}
