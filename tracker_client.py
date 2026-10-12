"""HTTP client for the wrp-pops Discord integration API."""

from __future__ import annotations

from typing import Any

import aiohttp


class TrackerError(Exception):
    """A tracker request failed. status is 0 for network errors and timeouts."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message

    @property
    def retryable(self) -> bool:
        return self.status == 0 or self.status >= 500


class TrackerClient:
    def __init__(self, base_url: str, token: str, *, timeout: float = 15.0):
        self.base_url = (base_url or "").rstrip("/")
        self.token = token or ""
        self.timeout = aiohttp.ClientTimeout(total=timeout)

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.token)

    def nation_url(self, path: str | None) -> str | None:
        if not path or not self.base_url:
            return None
        return f"{self.base_url}{path if path.startswith('/') else '/' + path}"

    async def _request(self, method: str, path: str, *, params: dict | None = None,
                       json: dict | None = None) -> Any:
        if not self.configured:
            raise TrackerError(0, "The population tracker integration is not configured.")
        url = f"{self.base_url}/api/integrations/discord/{path}"
        headers = {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}
        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.request(method, url, params=params, json=json, headers=headers) as resp:
                    try:
                        body = await resp.json(content_type=None)
                    except Exception:
                        body = None
                    if resp.status >= 400:
                        message = body.get("error") if isinstance(body, dict) else None
                        raise TrackerError(resp.status, message or f"Tracker returned HTTP {resp.status}.")
                    return body
        except TrackerError:
            raise
        except (aiohttp.ClientError, TimeoutError) as exc:
            raise TrackerError(0, f"Could not reach the population tracker: {exc or type(exc).__name__}") from exc

    async def regions(self) -> list[str]:
        body = await self._request("GET", "regions")
        return list(body.get("regions") or [])

    async def search_nations(self, query: str = "") -> list[dict]:
        body = await self._request("GET", "nations", params={"query": query or ""})
        return list(body.get("nations") or [])

    async def member_links(self, guild_id: int, member_id: int) -> list[dict]:
        body = await self._request("GET", "members", params={"guildId": str(guild_id), "memberId": str(member_id)})
        return list(body.get("links") or [])

    async def create_registration(self, *, guild_id: int, member_id: int, application_id: str,
                                  name: str, official_name: str, region: str, start_population: int,
                                  start_year: int, thread_id: int | None = None,
                                  registration_url: str | None = None) -> dict:
        payload: dict[str, Any] = {
            "guildId": str(guild_id),
            "memberId": str(member_id),
            "applicationId": application_id,
            "name": name,
            "officialName": official_name,
            "region": region,
            "startPopulation": int(start_population),
            "startYear": int(start_year),
        }
        if thread_id:
            payload["threadId"] = str(thread_id)
        if registration_url:
            payload["registrationUrl"] = registration_url
        return await self._request("POST", "registrations", json=payload)

    async def link_nation(self, *, guild_id: int, member_id: int, application_id: str,
                          nation_id: str, thread_id: int | None = None) -> dict:
        payload: dict[str, Any] = {
            "guildId": str(guild_id),
            "memberId": str(member_id),
            "applicationId": application_id,
            "nationId": nation_id,
        }
        if thread_id:
            payload["threadId"] = str(thread_id)
        return await self._request("POST", "links", json=payload)

    async def release_member(self, *, guild_id: int, member_id: int) -> dict:
        return await self._request("POST", "releases", json={"guildId": str(guild_id), "memberId": str(member_id)})
