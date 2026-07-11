"""AgentCenter REST API 客户端。"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Iterator

import httpx

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://127.0.0.1:8013"


class ApiError(Exception):
    def __init__(self, status: int, detail: str):
        self.status = status
        self.detail = detail
        super().__init__(f"HTTP {status}: {detail}")


class AgentCenterClient:
    def __init__(self, base_url: str | None = None, timeout: float = 30.0):
        self.base_url = (base_url or os.getenv("AGENTCENTER_URL", DEFAULT_BASE_URL)).rstrip(
            "/"
        )
        self.timeout = timeout
        logger.debug("API base_url=%s", self.base_url)

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        url = f"{self.base_url}{path}"
        logger.debug("%s %s params=%s", method, url, params)
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.request(method, url, params=params, json=json_body)
        if resp.status_code >= 400:
            detail = resp.text
            try:
                detail = resp.json().get("detail", detail)
            except Exception:
                pass
            raise ApiError(resp.status_code, str(detail))
        if resp.status_code == 204:
            return None
        if not resp.content:
            return None
        return resp.json()

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/api/health")

    def list_agents(self, refresh: bool = False) -> list[dict[str, Any]]:
        return self._request("GET", "/api/agents", params={"refresh": refresh})

    def get_agent(self, agent_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/agents/{agent_id}")

    def list_tasks(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        status: str | None = None,
        agent_id: str | None = None,
        project_id: str | None = None,
        workspace_id: str | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"page": page, "page_size": page_size}
        if status:
            params["status"] = status
        if agent_id:
            params["agent_id"] = agent_id
        if project_id:
            params["project_id"] = project_id
        if workspace_id:
            params["workspace_id"] = workspace_id
        return self._request("GET", "/api/tasks", params=params)

    def get_task(self, task_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/tasks/{task_id}")

    def create_task(self, body: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/api/tasks", json_body=body)

    def cancel_task(self, task_id: str) -> dict[str, Any]:
        return self._request("POST", f"/api/tasks/{task_id}/cancel")

    def retry_task(self, task_id: str) -> dict[str, Any]:
        return self._request("POST", f"/api/tasks/{task_id}/retry")

    def wait_task(
        self,
        task_id: str,
        *,
        poll_interval: float = 0.5,
        timeout: float = 600.0,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            task = self.get_task(task_id)
            status = task.get("status", "")
            if status in ("completed", "failed", "cancelled"):
                return task
            time.sleep(poll_interval)
        raise TimeoutError(f"task {task_id} did not finish within {timeout}s")

    def stream_task_events(self, task_id: str) -> Iterator[dict[str, Any]]:
        url = f"{self.base_url}/api/tasks/{task_id}/stream"
        with httpx.Client(timeout=None) as client:
            with client.stream("GET", url) as resp:
                if resp.status_code >= 400:
                    raise ApiError(resp.status_code, resp.text)
                event_type = "message"
                for line in resp.iter_lines():
                    if line.startswith("event:"):
                        event_type = line[6:].strip()
                    elif line.startswith("data:"):
                        data = line[5:].strip()
                        if event_type == "heartbeat":
                            continue
                        try:
                            payload = json.loads(data)
                        except json.JSONDecodeError:
                            payload = {"type": event_type, "content": data}
                        yield payload

    def list_squads(self) -> list[dict[str, Any]]:
        return self._request("GET", "/api/squads")

    def create_squad_task(self, squad_id: str, prompt: str, timeout: int | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"squad_id": squad_id, "prompt": prompt}
        if timeout is not None:
            body["timeout"] = timeout
        return self._request("POST", "/api/squads/tasks", json_body=body)

    def list_skills(self) -> list[dict[str, Any]]:
        return self._request("GET", "/api/skills")

    def list_autopilots(self) -> list[dict[str, Any]]:
        return self._request("GET", "/api/autopilots")

    def create_autopilot(
        self,
        name: str,
        agent_id: str,
        prompt: str,
        cron: str = "3600",
        enabled: bool = True,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/autopilots",
            json_body={
                "name": name,
                "agent_id": agent_id,
                "prompt": prompt,
                "cron": cron,
                "enabled": enabled,
            },
        )

    def trigger_autopilot(self, autopilot_id: str) -> dict[str, Any]:
        return self._request("POST", f"/api/autopilots/{autopilot_id}/trigger")

    def delete_autopilot(self, autopilot_id: str) -> None:
        self._request("DELETE", f"/api/autopilots/{autopilot_id}")

    def list_workspaces(self) -> list[dict[str, Any]]:
        return self._request("GET", "/api/workspaces")

    def list_projects(self, workspace_id: str | None = None) -> list[dict[str, Any]]:
        params = {"workspace_id": workspace_id} if workspace_id else None
        return self._request("GET", "/api/projects", params=params)
