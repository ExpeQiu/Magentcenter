/** 办公室关键路径日志。检索前缀 `[kanban-office]`。 */

export function officeLog(
  event: string,
  fields: Record<string, string | number | boolean | null | undefined> = {}
) {
  const payload: Record<string, string | number | boolean | null> = {
    event,
    at: new Date().toISOString(),
  };
  for (const [key, value] of Object.entries(fields)) {
    if (value !== undefined) payload[key] = value;
  }
  console.info("[kanban-office]", payload);
}
