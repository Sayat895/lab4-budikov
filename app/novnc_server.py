import asyncio

from aiohttp import WSMsgType, web


async def proxy_vnc(request):
    websocket = web.WebSocketResponse(max_msg_size=0, heartbeat=30)
    await websocket.prepare(request)

    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", 5900)
    except OSError:
        await websocket.close(message=b"VNC server is not ready")
        return websocket

    async def send_to_vnc():
        async for message in websocket:
            if message.type == WSMsgType.BINARY:
                writer.write(message.data)
            elif message.type == WSMsgType.TEXT:
                writer.write(message.data.encode("utf-8"))
            elif message.type in (WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.ERROR):
                break
            await writer.drain()

    async def send_to_browser():
        while data := await reader.read(65536):
            await websocket.send_bytes(data)

    tasks = {
        asyncio.create_task(send_to_vnc()),
        asyncio.create_task(send_to_browser()),
    }
    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)
    for task in done:
        if not task.cancelled() and task.exception() is not None:
            writer.close()
            raise task.exception()

    writer.close()
    await writer.wait_closed()
    if not websocket.closed:
        await websocket.close()
    return websocket


def create_app():
    app = web.Application()
    app.router.add_get("/websockify", proxy_vnc)
    app.router.add_static("/", "/usr/share/novnc", show_index=False)
    return app


if __name__ == "__main__":
    web.run_app(create_app(), host="0.0.0.0", port=6080, access_log=None)
