/** Skipped business stages are not cancelled tool executions. */
export function presentSop(items = []) {
  const active = items.filter((item) => item.status !== "skipped");
  return {
    active,
    skipped: items.filter((item) => item.status === "skipped").map((item) => item.text),
    done: active.filter((item) => item.status === "completed").length,
    total: active.length,
  };
}
