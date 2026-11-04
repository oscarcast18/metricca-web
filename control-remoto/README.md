# Control remoto de escritorio

Programa para ver y controlar tu PC desde otro dispositivo (laptop, tablet o celular) usando el navegador, al estilo de Chrome Remote Desktop.

- **Video:** WebRTC, la misma tecnología que usa Chrome Remote Desktop.
- **Control:** mouse, clic derecho, rueda, teclado y atajos (Ctrl+C, Alt+Tab en pantalla completa…).
- **Seguridad:** contraseña obligatoria, bloqueo tras 5 intentos fallidos y una sola sesión a la vez. El video y los eventos viajan cifrados (DTLS/SRTP).

## 1. Instalación (en la PC que quieres controlar)

Necesitas **Python 3.10 o superior** (en Windows, marca "Add Python to PATH" al instalarlo).

```bash
cd control-remoto
pip install -r requirements.txt
```

## 2. Uso

```bash
python host.py --password "una-clave-larga"
```

El programa muestra algo como:

```
=== Control remoto listo ===
  Abre en el otro dispositivo:  http://192.168.1.50:8765
  Contraseña:  una-clave-larga
```

Abre esa dirección en el otro dispositivo, escribe la contraseña y listo.
Si no pones `--password`, se genera una contraseña aleatoria cada vez.

| Opción | Para qué sirve |
|---|---|
| `--monitor 2` | Compartir otro monitor (1 = principal) |
| `--fps 30` | Más fluidez (consume más CPU y red) |
| `--max-width 1280` | Menor resolución: mejor en redes lentas o en el celular |
| `--view-only` | Solo ver, sin control |
| `--port 8765` | Cambiar el puerto |

En la página tienes:
- **Pantalla completa:** en Chrome también captura teclas como Esc y la tecla Windows.
- **⌨:** abre el teclado del celular.
- **Pegar texto:** escribe en la PC el texto de tu portapapeles.

## 3. Acceso desde fuera de tu casa u oficina

Por defecto funciona dentro de la **misma red** (Wi-Fi o LAN). Para conectarte desde internet, la opción recomendada es **[Tailscale](https://tailscale.com)**, que es gratis para uso personal:

1. Instala Tailscale en la PC y en el dispositivo remoto, con la misma cuenta.
2. Usa la IP de Tailscale de la PC (`100.x.x.x`): `http://100.x.x.x:8765`.

Así no tienes que abrir puertos en el router, y la conexión queda cifrada y limitada a tus dispositivos.
⚠️ **No expongas el puerto 8765 directamente a internet**. La página se sirve por HTTP; la contraseña solo va protegida si la conexión está dentro de tu red o de Tailscale.

## 4. Permisos según el sistema operativo

- **Windows:** funciona tal cual. Para controlar ventanas que se ejecutan como administrador, ejecuta `host.py` también como administrador. Si el Firewall pregunta, permite el acceso en redes privadas.
- **macOS:** en *Ajustes del sistema → Privacidad y seguridad*, dale a la Terminal (o a Python) permiso de **Grabación de pantalla** y de **Accesibilidad**.
- **Linux:** funciona con X11. En Wayland, la captura de pantalla y la simulación de entrada están restringidas; inicia una sesión "Xorg".

## Limitaciones conocidas

- No se envía audio.
- No se puede enviar **Ctrl+Alt+Supr** (Windows lo reserva por seguridad) ni controlar la pantalla de inicio de sesión o UAC sin ejecutar como servicio.
- El portapapeles solo va del cliente a la PC, con el botón "Pegar texto".
- La codificación de video es por software, así que en pantallas 4K conviene usar `--max-width 1920` o menos.

## Cómo funciona

```
Navegador (cliente)                         PC (host.py)
 ├─ POST /offer  (SDP + contraseña) ─────►  valida, crea la conexión WebRTC
 ◄─────────────── respuesta SDP ───────────┤
 ◄═════ video de pantalla (VP8/H.264) ═════ mss captura → aiortc codifica
 ══════ DataChannel "input" (JSON) ══════►  pynput mueve el mouse y pulsa teclas
```
