import asyncio
import logging
import os
import signal
from pathlib import Path

from aiohttp import WSMsgType, web


logger = logging.getLogger(__name__)
APPLICATION_PID_FILE = Path("/tmp/pyqt-app.pid")
NOVNC_UI_FILE = Path("/usr/share/novnc/app/ui.js")
KEYBOARD_SHORTCUT_BRIDGE = """
window.addEventListener("keydown", (event) => {
    if (!(event.ctrlKey || event.metaKey) || !UI.rfb) return;
    const target = event.target;
    if (target instanceof Element &&
        target.closest("input, textarea, select, button") &&
        target.id !== "noVNC_keyboardinput") return;

    const keyCode = event.code;
    let key = "";
    if (keyCode.startsWith("Key")) key = keyCode.slice(3).toLowerCase();
    else if (keyCode.startsWith("Digit")) key = keyCode.slice(5);
    if (!key) return;

    const keysym = keysyms.lookup(key.charCodeAt(0));
    if (!keysym) return;
    event.preventDefault();
    event.stopImmediatePropagation();

    const sendShortcut = () => {
        const modifiers = [];
        if (event.ctrlKey) modifiers.push([KeyTable.XK_Control_L, "ControlLeft"]);
        if (event.metaKey) modifiers.push([KeyTable.XK_Super_L, "MetaLeft"]);
        if (event.altKey) modifiers.push([KeyTable.XK_Alt_L, "AltLeft"]);
        if (event.shiftKey) modifiers.push([KeyTable.XK_Shift_L, "ShiftLeft"]);
        for (const [symbol, code] of modifiers) UI.rfb.sendKey(symbol, code, true);
        UI.rfb.sendKey(keysym, keyCode, true);
        UI.rfb.sendKey(keysym, keyCode, false);
        for (const [symbol, code] of modifiers.reverse()) UI.rfb.sendKey(symbol, code, false);
    };

    if (key === "v" && navigator.clipboard?.readText) {
        navigator.clipboard.readText().then((text) => {
            UI.rfb.clipboardPasteFrom(text);
            sendShortcut();
        }).catch((error) => {
            console.warn("Could not read the browser clipboard; using the remote clipboard.", error);
            sendShortcut();
        });
    } else {
        sendShortcut();
    }
}, true);

const clipboardSyncTimer = window.setInterval(() => {
    if (!UI.rfb) return;
    window.clearInterval(clipboardSyncTimer);
    UI.rfb.addEventListener("clipboard", (event) => {
        if (navigator.clipboard?.writeText) {
            navigator.clipboard.writeText(event.detail.text).catch((error) => {
                console.warn("Could not copy the remote clipboard to the browser.", error);
            });
        }
    });
}, 100);
"""


async def serve_novnc_ui(request):
    source = NOVNC_UI_FILE.read_text(encoding="utf-8")
    marker = "export default UI;"
    if source.count(marker) != 1:
        raise web.HTTPInternalServerError(text="Unexpected noVNC UI entry point")
    return web.Response(
        text=source.replace(marker, KEYBOARD_SHORTCUT_BRIDGE + "\n" + marker),
        content_type="application/javascript",
        headers={"Cache-Control": "no-store"},
    )


def request_reauthentication():
    reauthentication_signal = getattr(signal, "SIGUSR1", None)
    if reauthentication_signal is None:
        logger.error("This platform does not support the application reauthentication signal")
        return

    try:
        process_id = int(APPLICATION_PID_FILE.read_text(encoding="ascii").strip())
    except FileNotFoundError:
        return
    except ValueError:
        logger.error("The application PID file contains an invalid process ID")
        return

    command_line_path = Path("/proc") / str(process_id) / "cmdline"
    try:
        command_line = command_line_path.read_bytes().split(b"\0")
    except FileNotFoundError:
        return
    if b"/app/main.py" not in command_line:
        logger.warning("Skipped reauthentication because the PID does not belong to the app")
        return

    try:
        os.kill(process_id, reauthentication_signal)
    except ProcessLookupError:
        logger.info("The application exited before reauthentication was requested")


async def proxy_vnc(request):
    websocket = web.WebSocketResponse(max_msg_size=0, heartbeat=30)
    await websocket.prepare(request)

    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", 5900)
    except OSError:
        await websocket.close(message=b"VNC server is not ready")
        return websocket

    request_reauthentication()

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
    app.router.add_get("/app/ui.js", serve_novnc_ui)
    app.router.add_static("/", "/usr/share/novnc", show_index=False)
    return app


if __name__ == "__main__":
    web.run_app(create_app(), host="0.0.0.0", port=6080, access_log=None)
