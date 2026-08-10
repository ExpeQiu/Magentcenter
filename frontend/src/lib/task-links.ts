/** 任务详情 / Live Session 跳转 */

export function isLiveTaskId(id: string): boolean {
  return id.startsWith("live:");
}

/** live:openclaw:<sessionId> → sessionId */
export function liveSessionId(id: string): string | null {
  if (!isLiveTaskId(id)) return null;
  const parts = id.split(":");
  if (parts.length < 3) return null;
  return parts.slice(2).join(":");
}

export function taskHref(
  taskId: string,
  paths: { taskDetail: (id: string) => string; sessionDetail: (id: string) => string }
): string {
  const sid = liveSessionId(taskId);
  if (sid) return paths.sessionDetail(sid);
  return paths.taskDetail(taskId);
}
