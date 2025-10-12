import gi
import sys
import threading
import time
import socket

gi.require_version('Gst', '1.0')
from gi.repository import Gst, GObject, GLib

Gst.init(None)


class GStreamerPipeline:
    def __init__(self, pipeline_desc):
        self.pipeline = Gst.parse_launch(pipeline_desc)
        self.loop = GLib.MainLoop()
        self.bus = self.pipeline.get_bus()
        self.bus.add_signal_watch()
        self.bus.connect("message", self.on_message)
        self.thread = threading.Thread(target=self.run_pipeline, daemon=True)

    def on_message(self, bus, message):
        t = message.type
        if t == Gst.MessageType.EOS or t == Gst.MessageType.ERROR:
            if t == Gst.MessageType.ERROR:
                err, debug = message.parse_error()
                print(f"\n[GStreamer] Stream detenido. ERROR: {err} (debug: {debug})")
            else:
                print("\n[GStreamer] Stream detenido (EOS).")
            self.stop()
        return True

    def run_pipeline(self):
        # El loop.run() se ejecuta en el hilo separado
        self.pipeline.set_state(Gst.State.PLAYING)
        self.loop.run()

    def start(self):
        print("▶️ Iniciando reproducción en hilo separado...")
        self.thread.start()

    def stop(self):
        # Función para detener el loop y liberar recursos
        if self.loop.is_running():
            self.loop.quit()
        if self.pipeline:
            self.pipeline.set_state(Gst.State.NULL)


# --- Funciones de control remoto (cliente UDP) ---
def send_control_command(server_ip: str, server_port: int, message: str, timeout=1.0) -> bool:
    """Envía un comando UDP simple al servidor (CM4). Devuelve True si recibe 'OK'."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(timeout)
        s.sendto(message.encode(), (server_ip, server_port))
        try:
            resp, _ = s.recvfrom(1024)
            return resp.strip().upper() == b"OK"
        except socket.timeout:
            # No hubo respuesta, pero el comando pudo haberse recibido; informar al usuario
            print("⚠️ No se recibió ack del servidor (timeout).")
            return False
        finally:
            s.close()
    except Exception as e:
        print(f"❌ Error al enviar comando UDP: {e}")
        return False


def interactive_command_loop(server_ip: str, server_port: int):
    """Bucle interactivo para enviar comandos desde el cliente."""
    print("\nEscribe comandos para controlar LEDs en la CM4:")
    print("  on <pin>     -> enciende LED (ej: on 17)")
    print("  off <pin>    -> apaga LED")
    print("  toggle <pin> -> alterna estado")
    print("  set <pin> <0|1> -> fija estado")
    print("  quit         -> salir")
    try:
        while True:
            cmd = input("> ").strip()
            if not cmd:
                continue
            if cmd.lower() in ("quit", "exit"):
                break
            parts = cmd.split()
            if parts[0].lower() in ("on", "off", "toggle") and len(parts) >= 2:
                action = parts[0].upper()
                pin = parts[1]
                if action == "on":
                    msg = f"LED ON {pin}"
                elif action == "off":
                    msg = f"LED OFF {pin}"
                else:
                    msg = f"LED TOGGLE {pin}"
            elif parts[0].lower() == "set" and len(parts) >= 3:
                pin = parts[1]
                val = parts[2]
                msg = f"SET {pin} {val}"
            else:
                print("Comando inválido. Vea las instrucciones arriba.")
                continue

            ok = send_control_command(server_ip, server_port, msg)
            print("ACK" if ok else "NO ACK")
    except KeyboardInterrupt:
        print("\nInterrupción de usuario en el bucle de comandos.")


# --- Ejecución Principal ---
if __name__ == "__main__":

    # IP del servidor (Raspberry Pi CM4) a la que enviar comandos.
    # Ajusta esta IP a la dirección de tu CM4 en la red.
    RPI_SERVER_IP = "192.168.1.132"
    RPI_CONTROL_PORT = 6000

    PIPELINE_DESCRIPTION = (
        "udpsrc port=5000 caps=\"application/x-rtp, media=video, clock-rate=90000, encoding-name=H264, payload=96\" "
        "! rtph264depay ! h264parse ! decodebin ! videoconvert ! autovideosink"
    )

    client = GStreamerPipeline(PIPELINE_DESCRIPTION)
    client.start()

    print("✅ Cliente iniciado. Presiona Ctrl+C para detener el proceso principal.")
    print(f"🔁 Enviaré comandos UDP a {RPI_SERVER_IP}:{RPI_CONTROL_PORT} cuando uses el bucle interactivo.")

    # Arrancar el bucle de comandos en el hilo principal para que sea interactivo
    try:
        interactive_command_loop(RPI_SERVER_IP, RPI_CONTROL_PORT)

    except KeyboardInterrupt:
        print("\n[Ctrl+C detectado] Saliendo...")

    finally:
        client.stop()
        if client.thread.is_alive():
            client.thread.join(timeout=2)

    print("Programa finalizado y recursos liberados.")