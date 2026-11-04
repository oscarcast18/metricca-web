"""
Control remoto de escritorio (host).

Ejecuta este programa en la PC que quieres controlar. Sirve una página web;
ábrela desde otro dispositivo (http://IP-DE-ESTA-PC:8765), escribe la
contraseña y verás la pantalla y podrás usar mouse y teclado.

Video: WebRTC (aiortc) capturando la pantalla con mss.
Control: DataChannel de WebRTC -> pynput simula mouse y teclado.
"""

import argparse
import asyncio
import hmac
import json
import logging
import os
import secrets
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from fractions import Fraction
from pathlib import Path

# En Windows con escalado (125 %, 150 %...) hay que declarar DPI awareness ANTES
# de usar mss/pynput, para que captura y clics usen los mismos píxeles reales.
if sys.platform == "win32":
    import ctypes

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

import mss
import numpy as np
from aiohttp import web
from aiortc import RTCPeerConnection, RTCSessionDescription, VideoStreamTrack
from av import VideoFrame
from pynput.keyboard import Controller as KeyboardController
from pynput.keyboard import Key, KeyCode
from pynput.mouse import Button
from pynput.mouse import Controller as MouseController

log = logging.getLogger("control-remoto")
HERE = Path(__file__).resolve().parent
MSS = getattr(mss, "MSS", None) or mss.mss  # mss >= 10 renombró la clase


# --------------------------------------------------------------------------- #
# Captura de pantalla
# --------------------------------------------------------------------------- #
class ScreenCapture:
    """Captura un monitor en un hilo dedicado (mss no es seguro entre hilos)."""

    def __init__(self, monitor_index: int, max_width: int):
        self._executor = ThreadPoolExecutor(max_workers=1)
        self._local = threading.local()
        self.monitor_index = monitor_index
        self.max_width = max_width
        with MSS() as sct:
            if monitor_index >= len(sct.monitors):
                raise SystemExit(
                    f"El monitor {monitor_index} no existe. Hay "
                    f"{len(sct.monitors) - 1} monitor(es); usa --monitor 1..."
                )
            self.monitor = dict(sct.monitors[monitor_index])

    def _grab(self) -> np.ndarray:
        sct = getattr(self._local, "sct", None)
        if sct is None:
            sct = self._local.sct = MSS()
        return np.asarray(sct.grab(self.monitor))  # BGRA, alto x ancho x 4

    async def grab(self) -> np.ndarray:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, self._grab)

    def output_size(self) -> tuple[int, int]:
        w, h = self.monitor["width"], self.monitor["height"]
        if w > self.max_width:
            h = round(h * self.max_width / w)
            w = self.max_width
        return w - (w % 2), h - (h % 2)  # los códecs requieren dimensiones pares


class ScreenTrack(VideoStreamTrack):
    def __init__(self, capture: ScreenCapture, fps: int):
        super().__init__()
        self.capture = capture
        self.frame_time = 1 / fps
        self.time_base = Fraction(1, 90000)
        self._start = None
        self._pts = 0

    async def recv(self) -> VideoFrame:
        # Ritmo de cuadros propio para poder elegir los fps.
        if self._start is None:
            self._start = time.monotonic()
        else:
            self._pts += int(self.frame_time * 90000)
            wait = self._start + self._pts / 90000 - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)

        img = await self.capture.grab()
        frame = VideoFrame.from_ndarray(img, format="bgra")
        w, h = self.capture.output_size()
        frame = frame.reformat(width=w, height=h, format="yuv420p")
        frame.pts = self._pts
        frame.time_base = self.time_base
        return frame


# --------------------------------------------------------------------------- #
# Simulación de mouse y teclado
# --------------------------------------------------------------------------- #
SPECIAL_KEYS = {
    "Enter": Key.enter, "Backspace": Key.backspace, "Tab": Key.tab,
    "Escape": Key.esc, " ": Key.space, "Delete": Key.delete,
    "ArrowLeft": Key.left, "ArrowRight": Key.right,
    "ArrowUp": Key.up, "ArrowDown": Key.down,
    "Home": Key.home, "End": Key.end,
    "PageUp": Key.page_up, "PageDown": Key.page_down,
    "Shift": Key.shift, "Control": Key.ctrl, "Alt": Key.alt,
    "AltGraph": Key.alt_gr, "Meta": Key.cmd, "OS": Key.cmd,
    "CapsLock": Key.caps_lock,
    **{f"F{i}": getattr(Key, f"f{i}") for i in range(1, 13)},
}
for _name, _attr in (("Insert", "insert"), ("PrintScreen", "print_screen"),
                     ("ContextMenu", "menu"), ("NumLock", "num_lock"),
                     ("Pause", "pause"), ("ScrollLock", "scroll_lock")):
    if hasattr(Key, _attr):
        SPECIAL_KEYS[_name] = getattr(Key, _attr)

BUTTONS = {0: Button.left, 1: Button.middle, 2: Button.right}


class InputController:
    def __init__(self, capture: ScreenCapture, view_only: bool):
        self.mon = capture.monitor
        self.view_only = view_only
        self.mouse = MouseController()
        self.keyboard = KeyboardController()
        self.pressed_keys = set()
        self.pressed_buttons = set()

    def _key(self, msg):
        k = msg.get("key", "")
        if k in SPECIAL_KEYS:
            return SPECIAL_KEYS[k]
        if len(k) == 1:
            return KeyCode.from_char(k)
        return None

    def _move(self, msg):
        x = min(max(float(msg["x"]), 0.0), 1.0)
        y = min(max(float(msg["y"]), 0.0), 1.0)
        self.mouse.position = (
            self.mon["left"] + round(x * (self.mon["width"] - 1)),
            self.mon["top"] + round(y * (self.mon["height"] - 1)),
        )

    def handle(self, raw: str):
        if self.view_only:
            return
        try:
            msg = json.loads(raw)
            t = msg.get("t")
            if t == "move":
                self._move(msg)
            elif t in ("down", "up"):
                if "x" in msg:
                    self._move(msg)
                btn = BUTTONS.get(int(msg.get("b", 0)))
                if btn is None:
                    return
                if t == "down":
                    self.mouse.press(btn)
                    self.pressed_buttons.add(btn)
                else:
                    self.mouse.release(btn)
                    self.pressed_buttons.discard(btn)
            elif t == "wheel":
                # El navegador da píxeles; pynput usa "clics" de rueda.
                dx = -int(round(float(msg.get("dx", 0)) / 100))
                dy = -int(round(float(msg.get("dy", 0)) / 100))
                if dx or dy:
                    self.mouse.scroll(dx, dy)
            elif t in ("kd", "ku"):
                key = self._key(msg)
                if key is None:
                    return
                if t == "kd":
                    self.keyboard.press(key)
                    self.pressed_keys.add(key)
                else:
                    self.keyboard.release(key)
                    self.pressed_keys.discard(key)
            elif t == "type":
                self.keyboard.type(str(msg.get("text", ""))[:2000])
            elif t == "release-all":
                self.release_all()
        except Exception as exc:  # un mensaje malo no debe tumbar la sesión
            log.warning("Evento de entrada inválido %r: %s", raw[:200], exc)

    def release_all(self):
        """Evita teclas o botones 'pegados' si se corta la conexión."""
        for key in list(self.pressed_keys):
            try:
                self.keyboard.release(key)
            except Exception:
                pass
        for btn in list(self.pressed_buttons):
            try:
                self.mouse.release(btn)
            except Exception:
                pass
        self.pressed_keys.clear()
        self.pressed_buttons.clear()


# --------------------------------------------------------------------------- #
# Servidor web + señalización
# --------------------------------------------------------------------------- #
class Host:
    def __init__(self, args):
        self.args = args
        self.password = args.password
        self.capture = ScreenCapture(args.monitor, args.max_width)
        self.input = InputController(self.capture, args.view_only)
        self.pc: RTCPeerConnection | None = None
        self.failed: dict[str, list[float]] = {}

    def _rate_limited(self, ip: str) -> bool:
        now = time.monotonic()
        attempts = [t for t in self.failed.get(ip, []) if now - t < 300]
        self.failed[ip] = attempts
        return len(attempts) >= 5  # 5 intentos fallidos cada 5 minutos

    async def index(self, request):
        return web.FileResponse(HERE / "client.html")

    async def offer(self, request):
        ip = request.remote or "?"
        if self._rate_limited(ip):
            return web.json_response({"error": "Demasiados intentos. Espera 5 minutos."}, status=429)
        try:
            params = await request.json()
            sdp, typ = params["sdp"], params["type"]
            given = str(params.get("password", ""))
        except Exception:
            return web.json_response({"error": "Solicitud inválida"}, status=400)

        if not hmac.compare_digest(given.encode(), self.password.encode()):
            self.failed.setdefault(ip, []).append(time.monotonic())
            log.warning("Contraseña incorrecta desde %s", ip)
            return web.json_response({"error": "Contraseña incorrecta"}, status=403)

        # Una sola sesión a la vez: la nueva reemplaza a la anterior.
        if self.pc is not None:
            log.info("Cerrando la sesión anterior")
            await self._close_pc(self.pc)

        pc = RTCPeerConnection()
        self.pc = pc
        log.info("Sesión iniciada desde %s", ip)

        @pc.on("datachannel")
        def on_datachannel(channel):
            channel.on("message", lambda m: self.input.handle(m) if isinstance(m, str) else None)
            channel.send(json.dumps({"t": "info", "viewOnly": self.args.view_only}))

        @pc.on("connectionstatechange")
        async def on_state():
            log.info("Conexión: %s", pc.connectionState)
            if pc.connectionState in ("failed", "closed"):
                await self._close_pc(pc)

        pc.addTrack(ScreenTrack(self.capture, self.args.fps))
        await pc.setRemoteDescription(RTCSessionDescription(sdp=sdp, type=typ))
        await pc.setLocalDescription(await pc.createAnswer())
        return web.json_response({"sdp": pc.localDescription.sdp, "type": pc.localDescription.type})

    async def _close_pc(self, pc):
        self.input.release_all()
        if self.pc is pc:
            self.pc = None
        await pc.close()

    async def on_shutdown(self, app):
        if self.pc is not None:
            await self._close_pc(self.pc)


def local_ips() -> list[str]:
    import socket

    ips = set()
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))  # no envía nada, solo elige la interfaz
            ips.add(s.getsockname()[0])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    return sorted(ip for ip in ips if not ip.startswith("127.")) or ["127.0.0.1"]


def main():
    p = argparse.ArgumentParser(description="Control remoto de escritorio (host)")
    p.add_argument("--host", default="0.0.0.0", help="Interfaz donde escuchar (por defecto todas)")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--password", default=os.environ.get("CONTROL_REMOTO_PASSWORD"),
                   help="Contraseña de acceso (o variable CONTROL_REMOTO_PASSWORD). "
                        "Si no se indica, se genera una al azar.")
    p.add_argument("--monitor", type=int, default=1, help="Monitor a compartir (1 = principal)")
    p.add_argument("--fps", type=int, default=20)
    p.add_argument("--max-width", type=int, default=1920,
                   help="Ancho máximo del video; menos = más fluido en redes lentas")
    p.add_argument("--view-only", action="store_true", help="Solo ver, sin control")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("aiortc").setLevel(logging.WARNING)
    logging.getLogger("aioice").setLevel(logging.WARNING)

    if not args.password:
        args.password = secrets.token_urlsafe(9)
    elif len(args.password) < 8:
        raise SystemExit("La contraseña debe tener al menos 8 caracteres.")

    host = Host(args)
    app = web.Application(client_max_size=256 * 1024)
    app.router.add_get("/", host.index)
    app.router.add_post("/offer", host.offer)
    app.on_shutdown.append(host.on_shutdown)

    print("\n=== Control remoto listo ===")
    for ip in local_ips():
        print(f"  Abre en el otro dispositivo:  http://{ip}:{args.port}")
    print(f"  Contraseña:  {args.password}")
    print(f"  Monitor: {args.monitor}  {host.capture.monitor['width']}x{host.capture.monitor['height']}"
          f"{'  (solo ver)' if args.view_only else ''}")
    print("  Ctrl+C para detener.\n")
    web.run_app(app, host=args.host, port=args.port, print=None)


if __name__ == "__main__":
    main()
