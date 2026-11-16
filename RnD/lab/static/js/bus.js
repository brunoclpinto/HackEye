// Tiny synchronous event bus: how features call each other without importing each other.
// on(name, fn) registers a handler; emit(name, ...args) runs every handler in registration order and returns
// the first handler's return value (a promise for async handlers; undefined when nobody listens).
const handlers = new Map();

export function on(name, fn) {
  if (!handlers.has(name)) handlers.set(name, []);
  handlers.get(name).push(fn);
}

export function emit(name, ...args) {
  const list = handlers.get(name) ?? [];
  const results = list.map((fn) => fn(...args));
  return results[0];
}
