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
        self.pipeline.set_state(Gst.State.PLAYING)
        self.loop.run()

    def start(self):
        print("▶️ Iniciando reproducción de video en hilo separado...")
        self.thread.start()

    def stop(self):
        if self.loop.is_running():
            self.loop.quit()
        if self.pipeline:
            self.pipeline.set_state(Gst.State.NULL)


# --- Funciones de control remoto (cliente UDP) ---
def send_control_command(server_ip: str, server_port: int, message: str, timeout=1.0) -> bool:
    """Envía un comando UDP simple al servidor. Devuelve True si recibe 'OK'."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(timeout)
        s.sendto(message.encode(), (server_ip, server_port))
        try:
            resp, _ = s.recvfrom(1024)
            return resp.strip().upper() == b"OK"
        except socket.timeout:
            print("⚠️ No se recibió ack del servidor (timeout).")
            return False
        finally:
            s.close()
    except Exception as e:
        print(f"❌ Error al enviar comando UDP: {e}")
        return False


def interactive_command_loop(server_ip: str, server_port: int):
    """Bucle interactivo adaptado EXCLUSIVAMENTE para enviar comandos de Servo."""
    print("\n" + "="*45)
    print("🎮 CONTROL DE SERVOS ACTIVADO")
    print("="*45)
    print("Escribe el comando en este formato:")
    print("  servo <canal> <ángulo>")
    print("\nEjemplos:")
    print("  servo 0 90    -> Mueve el servo del canal 0 a 90 grados")
    print("  servo 3 180   -> Mueve el servo del canal 3 a 180 grados")
    print("  quit          -> Para salir")
    print("="*45 + "\n")
    
    try:
        while True:
            cmd = input("Control_Servo > ").strip()
            if not cmd:
                continue
            
            if cmd.lower() in ("quit", "exit"):
                break
                
            parts = cmd.split()
            
            # Validamos que el comando empiece por "servo" y tenga 3 partes
            if parts[0].lower() == "servo" and len(parts) == 3:
                try:
                    # Validamos que los parámetros sean números antes de enviar
                    channel = int(parts[1])
                    angle = float(parts[2])
                    
                    # Formateamos el mensaje tal como lo espera la Raspberry Pi
                    msg = f"SERVO {channel} {angle}"
                    
                    # Enviamos el comando
                    ok = send_control_command(server_ip, server_port, msg)
                    print("✅ Comando aceptado (ACK)" if ok else "❌ Fallo en la comunicación (NO ACK)")
                    
                except ValueError:
                    print("⚠️ Error: El canal y el ángulo deben ser números (Ej: servo 0 90)")
            else:
                print("⚠️ Comando inválido. Usa el formato: servo <canal> <ángulo>")
                
    except KeyboardInterrupt:
        print("\nInterrupción de usuario en el bucle de comandos.")


# --- Ejecución Principal ---
if __name__ == "__main__":

    # IP de la Raspberry Pi (Asegúrate de que sea la correcta)
    RPI_SERVER_IP = "192.168.8.147" 
    RPI_CONTROL_PORT = 6000

    # --- CAMBIO PRINCIPAL PARA JETSON ORIN NANO ---
    # Se reemplaza 'decodebin ! videoconvert ! autovideosink' por aceleración por hardware
    # 'nvv4l2decoder' usa el decodificador de video por hardware de la Jetson
    # 'nv3dsink sync=false' renderiza el video sin forzar sincronización de reloj, ideal para baja latencia
    PIPELINE_DESCRIPTION = (
        "udpsrc port=5002 caps=\"application/x-rtp, media=video, clock-rate=90000, encoding-name=H264, payload=96\" "
        "! rtph264depay ! h264parse ! nvv4l2decoder ! nvvidconv ! nv3dsink sync=false"
    )

    client = GStreamerPipeline(PIPELINE_DESCRIPTION)
    client.start()

    # Corregido el mensaje del puerto para que coincida con el udpsrc (5002)
    print(f"✅ Cliente de video iniciado escuchando en el puerto 5002.")
    print(f"🔁 Los comandos de control se enviarán a {RPI_SERVER_IP}:{RPI_CONTROL_PORT}.")

    try:
        # Iniciamos el menú interactivo para los servos
        interactive_command_loop(RPI_SERVER_IP, RPI_CONTROL_PORT)

    except KeyboardInterrupt:
        print("\n[Ctrl+C detectado] Saliendo...")

    finally:
        client.stop()
        if client.thread.is_alive():
            client.thread.join(timeout=2)

    print("Programa finalizado y recursos liberados.")
