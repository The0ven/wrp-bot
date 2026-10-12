import socket

import pytest
from aiohttp import web

from tracker_client import TrackerClient, TrackerError

TOKEN = "secret-token"


async def start_server(seen):
    async def regions(request):
        seen["auth"] = request.headers.get("Authorization")
        seen["accept"] = request.headers.get("Accept")
        return web.json_response({"regions": ["North", "South"]})

    async def nations(request):
        seen["query"] = request.query.get("query")
        return web.json_response({"nations": [{"id": "n1", "name": "Avalon"}]})

    async def members(request):
        seen["member_query"] = dict(request.query)
        return web.json_response({"links": []})

    async def registrations(request):
        seen["payload"] = await request.json()
        if seen["payload"].get("name") == "Taken":
            return web.json_response({"error": "Nation name already exists."}, status=409)
        return web.json_response({"nation": {"id": "n9"}, "nationPath": "/nations/n9", "created": True})

    async def releases(request):
        return web.Response(status=500, text="<html>boom</html>")

    app = web.Application()
    base = "/api/integrations/discord/"
    app.router.add_get(base + "regions", regions)
    app.router.add_get(base + "nations", nations)
    app.router.add_get(base + "members", members)
    app.router.add_post(base + "registrations", registrations)
    app.router.add_post(base + "releases", releases)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    return runner, f"http://127.0.0.1:{port}"


@pytest.mark.asyncio
async def test_get_requests_send_auth_and_query():
    seen = {}
    runner, url = await start_server(seen)
    try:
        client = TrackerClient(url + "/", TOKEN)
        assert client.configured
        assert await client.regions() == ["North", "South"]
        assert seen["auth"] == "Bearer " + TOKEN
        assert seen["accept"] == "application/json"
        nations = await client.search_nations("Ava lon")
        assert nations[0]["id"] == "n1"
        assert seen["query"] == "Ava lon"
        assert await client.member_links(1, 2) == []
        assert seen["member_query"] == {"guildId": "1", "memberId": "2"}
        assert client.nation_url("/nations/n1") == url + "/nations/n1"
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_create_registration_payload_and_errors():
    seen = {}
    runner, url = await start_server(seen)
    try:
        client = TrackerClient(url, TOKEN)
        result = await client.create_registration(
            guild_id=1,
            member_id=2,
            application_id="app-3",
            name="Avalon",
            official_name="Kingdom of Avalon",
            region="North",
            start_population=1000,
            start_year=1200,
            thread_id=4,
        )
        assert result["nation"]["id"] == "n9"
        payload = seen["payload"]
        assert payload["guildId"] == "1"
        assert payload["memberId"] == "2"
        assert payload["applicationId"] == "app-3"
        assert payload["startPopulation"] == 1000
        assert payload["startYear"] == 1200
        assert payload["region"] == "North"

        with pytest.raises(TrackerError) as conflict:
            await client.create_registration(
                guild_id=1,
                member_id=2,
                application_id="app-3",
                name="Taken",
                official_name="Taken",
                region="North",
                start_population=1,
                start_year=1,
            )
        assert conflict.value.status == 409
        assert "already exists" in str(conflict.value.message)
        assert not conflict.value.retryable

        with pytest.raises(TrackerError) as server_error:
            await client.release_member(guild_id=1, member_id=2)
        assert server_error.value.status == 500
        assert server_error.value.retryable
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_unreachable_tracker_is_retryable():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    client = TrackerClient(f"http://127.0.0.1:{port}", TOKEN, timeout=2)
    with pytest.raises(TrackerError) as err:
        await client.regions()
    assert err.value.status == 0
    assert err.value.retryable


@pytest.mark.asyncio
async def test_unconfigured_client():
    client = TrackerClient("", "")
    assert not client.configured
    with pytest.raises(TrackerError) as err:
        await client.regions()
    assert err.value.status == 0
