import os
import signal
import subprocess
import time
import threading
import socket

# --- Configuración del Stream ---
CLIENT_IP = "192.168.8.100"
PORT = "5002"
BITRATE = "2000000"

CONTROL_PORT = 6000
CONTROL_HOST = "0.0.0.0"

STREAM_COMMAND = (
    f"rpicam-vid -t 0 --width 1920 --height 1080 --framerate 15 --codec h264 --inline --bitrate {BITRATE} -o - | "
    f"gst-launch-1.0 -v fdsrc ! h264parse ! rtph264pay config-interval=1 pt=96 ! udpsink host={CLIENT_IP} port={PORT} sync=false"
)

# --- Controlador de Servos ---
class ServoController:
    """Control de la placa PCA9685 usando adafruit_servokit."""
    def __init__(self, channels=16):
        self._use_servo = False
        try:
            from adafruit_servokit import ServoKit
            self.pca = ServoKit(channels=channels)
            self._use_servo = True
            print("PCA9685 detectado y configurado para servos.")
        except Exception as e:
            print(f"No se pudo inicializar PCA9685: {e}. Usando modo mock para servos.")

    def set_angle(self, channel, angle):
        """Ajusta el ángulo de un servo específico."""
        if not (0 <= channel <= 15):
            print("Canal de servo inválido. Debe ser de 0 a 15.")
            return False
            
        safe_angle = max(0, min(180, angle))
        
        if self._use_servo:
            try:
                self.pca.servo[channel].angle = safe_angle
            except ValueError as ve:
                print(f"Error al mover servo: {ve}")
                return False
                
        print(f"   -> Servo canal {channel} movido a {safe_angle} grados")
        return True
        
    def disable(self, channel):
        """Desactiva un canal para que el servo no haga fuerza."""
        if self._use_servo and (0 <= channel <= 15):
            self.pca.servo[channel].angle = None
        return True

# --- Servidor UDP ---
class ControlServer(threading.Thread):
    def __init__(self, host, port, servo_controller):
        super().__init__(daemon=True)
        self.host = host
        self.port = port
        self.servo = servo_controller
        self.running = False
        self.sock = None

    def run(self):
        self.running = True
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.sock.bind((self.host, self.port))
        except Exception as e:
            print(f"No se pudo abrir socket UDP: {e}")
            self.running = False
            return
        print(f"Servidor de control UDP escuchando en {self.host}:{self.port}")

        while self.running:
            try:
                self.sock.settimeout(1.0)
                data, addr = self.sock.recvfrom(1024)
            except socket.timeout:
                continue
            except OSError:
                break
            if not data:
                continue
            msg = data.decode(errors="ignore").strip()
            ok = self.handle_command(msg)
            try:
                self.sock.sendto(b"OK" if ok else b"ERR", addr)
            except Exception:
                pass

        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass

    def handle_command(self, msg: str) -> bool:
        """Formato aceptado: SERVO <canal> <ángulo> (ej: SERVO 0 90)"""
        parts = msg.upper().split()
        if not parts:
            return False

        if parts[0] == "SERVO":
            if len(parts) < 3:
                print("Formato inválido. Uso: SERVO <canal> <ángulo>")
                return False
            try:
                channel = int(parts[1])
                angle = float(parts[2])
            except ValueError:
                print("Canal o ángulo inválido.")
                return False
            return self.servo.set_angle(channel, angle)
        else:
            print("Comando no reconocido. Use SERVO.")
            return False

    def stop(self):
        self.running = False
        try:
            if self.sock:
                self.sock.sendto(b"", (self.host if self.host != "0.0.0.0" else "127.0.0.1", self.port))
        except Exception:
            pass

# --- Funciones de Streaming ---
def start_stream():
    print("Iniciando streaming de cámara...")
    process = subprocess.Popen(STREAM_COMMAND, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, preexec_fn=os.setsid)
    print(f"Streaming iniciado. PID: {process.pid}")
    return process

def stop_stream(process):
    print("\nDeteniendo streaming...")
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        try: process.wait(timeout=5)
        except subprocess.TimeoutExpired: os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        print("Streaming detenido correctamente.")
    except Exception as e:
        try:
            process.terminate()
            process.wait(timeout=5)
        except Exception: pass


if __name__ == "__main__":
    stream_process = None
    control_server = None
    
    servo_ctrl = ServoController()

    try:
        control_server = ControlServer(CONTROL_HOST, CONTROL_PORT, servo_ctrl)
        control_server.start()

        stream_process = start_stream()

        print("\n=== Sistema Listo ===")
        print("Esperando comandos UDP (Ej: 'SERVO 0 90')")
        print("Presiona Ctrl+C para salir.")

        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        pass

    finally:
        if stream_process and stream_process.poll() is None:
            stop_stream(stream_process)

        if control_server:
            control_server.stop()
            control_server.join(timeout=2)
        
        # Apaga los servos al salir para que no se quemen
        for i in range(16):
            servo_ctrl.disable(i)

    print("Programa finalizado.")