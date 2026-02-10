import os
import signal
import subprocess
import shlex
import time
import threading
import socket

# --- Configuración del Stream ---
# CLIENT_IP es la IP del receptor (tu laptop/PC). Cambia esto según tu red.
CLIENT_IP = "10.157.78.170"
PORT = "5000"
BITRATE = "2000000"

# Puerto para el canal de control (comandos UDP desde el cliente hacia la CM4)
CONTROL_PORT = 6000
CONTROL_HOST = "0.0.0.0"  # escuchar en todas las interfaces

# Pines GPIO (BCM) que controlarán los LEDs en la CM4.
# Ajusta la lista según los pines que tengas conectados a los LEDs.
LED_PINS = [23, 22, 6]

# Comando de streaming: rpicam-vid -> gst-launch -> udpsink
STREAM_COMMAND = (
    f"rpicam-vid -t 0 --width 1920 --height 1080 --framerate 15 --codec h264 --inline --bitrate {BITRATE} -o - | "
    f"gst-launch-1.0 -v fdsrc ! h264parse ! rtph264pay config-interval=1 pt=96 ! udpsink host={CLIENT_IP} port={PORT} sync=false"
)


class GPIOController:
    """Control básico de pines GPIO para LEDs con RPi.GPIO si está disponible.
    Si RPi.GPIO no está disponible, hace un 'mock' para evitar excepciones durante pruebas en otra máquina.
    """
    def __init__(self, pins):
        self.pins = pins
        self._use_gpio = False
        self._states = {pin: False for pin in pins}

        try:
            import RPi.GPIO as GPIO
            self.GPIO = GPIO
            self.GPIO.setmode(GPIO.BCM)
            for p in pins:
                self.GPIO.setup(p, self.GPIO.OUT, initial=self.GPIO.LOW)
                self._states[p] = False
            self._use_gpio = True
            print("RPi.GPIO detectado y configurado.")
        except Exception as e:
            # Fallback: mock behavior (útil para pruebas en PC)
            print(f "RPi.GPIO no está disponible: {e}. Usando modo mock (no cambiará hardware).")

    def set(self, pin, value: bool):
        if pin not in self.pins:
            print(f"in {pin} no está en la lista de LEDs configurada.")
            return False
        self._states[pin] = bool(value)
        if self._use_gpio:
            self.GPIO.output(pin, self.GPIO.HIGH if value else self.GPIO.LOW)
        print(f"   -> LED pin {pin} = {'ON' if value else 'OFF'}")
        return True

    def toggle(self, pin):
        if pin not in self.pins:
            print(f"in {pin} no está en la lista de LEDs configurada.")
            return False
        newval = not self._states[pin]
        return self.set(pin, newval)

    def cleanup(self):
        if self._use_gpio:
            self.GPIO.cleanup()
        print("GPIO limpiado.")


class ControlServer(threading.Thread):
    """Servidor UDP que recibe comandos simples para controlar LEDs."""
    def __init__(self, host, port, gpio_controller):
        super().__init__(daemon=True)
        self.host = host
        self.port = port
        self.gpio = gpio_controller
        self.running = False
        self.sock = None

    def run(self):
        self.running = True
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Reusar dirección para reinicios rápidos
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.sock.bind((self.host, self.port))
        except Exception as e:
            print(f"No se pudo abrir socket UDP en {self.host}:{self.port}: {e}")
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
            print(f"Comando recibido de {addr}: '{msg}'")
            ok = self.handle_command(msg)
            # Enviar ack simple
            try:
                self.sock.sendto(b"OK" if ok else b"ERR", addr)
            except Exception:
                pass

        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
        print("Servidor de control detenido.")

    def handle_command(self, msg: str) -> bool:
        """Formas de mensaje aceptadas:
        - LED ON <pin>
        - LED OFF <pin>
        - LED TOGGLE <pin>
        - SET <pin> <0|1>
        - ejemplos: 'LED ON 17'  'SET 27 1'
        """
        parts = msg.upper().split()
        if not parts:
            return False

        # Soportar variantes
        if parts[0] in ("LED",):
            if len(parts) < 3:
                print("Formato inválido. Uso: LED <ON|OFF|TOGGLE> <pin>")
                return False
            action = parts[1]
            try:
                pin = int(parts[2])
            except ValueError:
                print("Pin inválido, debe ser número BCM.")
                return False

            if action == "ON":
                return self.gpio.set(pin, True)
            elif action == "OFF":
                return self.gpio.set(pin, False)
            elif action == "TOGGLE":
                return self.gpio.toggle(pin)
            else:
                print("Acción desconocida. ON/OFF/TOGGLE.")
                return False

        elif parts[0] in ("SET",):
            if len(parts) < 3:
                print("Formato inválido. Uso: SET <pin> <0|1>")
                return False
            try:
                pin = int(parts[1])
                val = int(parts[2])
            except ValueError:
                print("Pin o valor inválido.")
                return False
            return self.gpio.set(pin, bool(val))

        else:
            print("Comando no reconocido. Use LED o SET.")
            return False

    def stop(self):
        self.running = False
        # cerrar socket para salir rápidamente del recv
        try:
            if self.sock:
                # enviar datagrama a sí mismo para desbloquear recvfrom si está en espera
                self.sock.sendto(b"", (self.host if self.host != "0.0.0.0" else "127.0.0.1", self.port))
        except Exception:
            pass


def start_stream():
    """Inicia la tubería de streaming como un proceso secundario en su propio grupo."""
    print("Iniciando streaming de cámara...")

    # Lanzar proceso en un nuevo grupo de procesos para poder matarlo junto con sus hijos
    process = subprocess.Popen(
        STREAM_COMMAND,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        preexec_fn=os.setsid  # en Unix, crea un nuevo pgid = pid del proceso hijo
    )
    print(f"Streaming iniciado. PID: {process.pid}")
    return process


def stop_stream(process):
    """Detiene el proceso de streaming enviando SIGTERM al grupo de procesos."""
    print("\nDeteniendo streaming...")
    try:
        # matar el grupo entero
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        # esperar un poco y forzar si no muere
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        print("Streaming detenido correctamente.")
    except Exception as e:
        print(f"rror al detener el proceso: {e}")
        try:
            process.terminate()
            process.wait(timeout=5)
            print("Streaming detenido (por terminate).")
        except Exception as e2:
            print(f"No se pudo detener el proceso: {e2}")


if __name__ == "__main__":
    stream_process = None
    control_server = None
    gpio_ctrl = GPIOController(LED_PINS)

    try:
        # Iniciar servidor de control UDP (antes del stream)
        control_server = ControlServer(CONTROL_HOST, CONTROL_PORT, gpio_ctrl)
        control_server.start()

        # Iniciar streaming
        stream_process = start_stream()

        print("\n El sistema está listo. El cliente puede enviar comandos UDP para controlar LEDs.")
        print("   Formatos aceptados: 'LED ON 17', 'LED OFF 17', 'LED TOGGLE 17', 'SET 17 1'")
        print("   Presiona Ctrl+C para detener el streaming y el script.")

        # Bucle principal: aquí puedes hacer otras tareas (control motores, etc.)
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        pass

    finally:
        # Parar streaming si sigue vivo
        if stream_process and stream_process.poll() is None:
            stop_stream(stream_process)

        # Parar servidor de control
        if control_server:
            control_server.stop()
            control_server.join(timeout=2)

        # Limpiar GPIO
        gpio_ctrl.cleanup()

    print("Programa finalizado.")
