/** Minimal hash-based router. Two routes only: test-runner (default) and playground. */

export type Route = "test-runner" | "playground";

export function currentRoute(): Route {
  return location.hash.startsWith("#/playground") ? "playground" : "test-runner";
}

export function navigate(r: Route): void {
  const next = r === "playground" ? "#/playground" : "#/";
  if (location.hash !== next) location.hash = next;
}

export function onRouteChange(cb: () => void): void {
  window.addEventListener("hashchange", cb);
}
