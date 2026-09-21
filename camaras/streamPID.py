import os
import signal
import subprocess
import time
import threading
import socket

# --- Configuración del Stream ---
CLIENT_IP = "192.168.8.175"
PORT = "5003"
BITRATE = "2000000"

CONTROL_PORT = 6000
CONTROL_HOST = "0.0.0.0"

STREAM_COMMAND = (
    f"rpicam-vid -t 0 --width 720 --height 480 --framerate 10 "
    f"--bitrate {BITRATE} --intra 10 --inline --codec h264 -o - | "
    f"gst-launch-1.0 -v fdsrc ! h264parse ! rtph264pay config-interval=1 pt=96 ! "
    f"udpsink host={CLIENT_IP} port={PORT} sync=false async=false"
)

class ServoController:
    """Control de la placa PCA9685 usando adafruit_servokit."""
    def __init__(self, channels=16):
        self._use_servo = False
        try:
            from adafruit_servokit import ServoKit
            self.pca = ServoKit(channels=channels)
            
            calibraciones = {
                0: (500, 2400),
                1: (750, 2500),
            }
            
            for canal, (p_min, p_max) in calibraciones.items():
                self.pca.servo[canal].set_pulse_width_range(p_min, p_max)
            
            self._use_servo = True
            print("PCA9685 detectado y configurado para servos.")
        except Exception as e:
            print(f"No se pudo inicializar PCA9685: {e}. Usando modo mock para servos.")

    def set_angle(self, channel, angle):
        """Ajusta el ángulo de un servo específico."""
        if not (0 <= channel <= 15):
            print("Canal de servo inválido. Debe ser de 0 a 15.")
            return False
        offsets = {0: 0, 1: 0}
        offset = offsets.get(channel, 0)
        anguloC = angle + offset
        safe_angle = max(0, min(180, anguloC))
        
        if self._use_servo:
            try:
                self.pca.servo[channel].angle = safe_angle
            except ValueError as ve:
                print(f"Error al mover servo: {ve}")
                return False
                
        print(f"   -> Servo canal {channel} movido a {safe_angle:.2f} grados")
        return True
        
    def disable(self, channel):
        """Desactiva un canal para que el servo no haga fuerza."""
        if self._use_servo and (0 <= channel <= 15):
            self.pca.servo[channel].angle = None
        return True

class ServoTracker:
    """Lógica de control Proporcional y PID ejecutada localmente en la RPi."""
    def __init__(self, servo_controller):
        self.servo = servo_controller
        self.FRAME_W, self.FRAME_H = 640, 360
        self.CENTER_X = self.FRAME_W / 2
        self.CENTER_Y = self.FRAME_H / 2
        
        self.pan_angle = 90.0  # Servo 1 (Centro)
        self.tilt_angle = 90.0 # Servo 0 (Centro)
        
        # Constantes de Control PID para PAN
        self.Kp_pan = 0.015
        self.Ki_pan = 0.001
        self.Kd_pan = 0.01

        # Constantes de Control PID para TILT
        self.Kp_tilt = 0.01
        self.Ki_tilt = 0.0
        self.Kd_tilt = 0.01
        
        # Variables de estado PID
        self.prev_error_x = 0.0
        self.integral_x = 0.0
        self.prev_error_y = 0.0
        self.integral_y = 0.0
        
        self.max_integral = 100.0
        self.deadzone = 20
        
        self.last_update = time.time()
        self.last_target_time = time.time() # Registra cuándo se vio el dron por última vez
        self.update_rate = 0.1

        # Configuración de modo escaneo (Lost)
        self.pan_sweep_dir = 1
        self.pan_sweep_speed = 1.0 # Velocidad de paneo en grados por ciclo

        # Posición inicial
        self.servo.set_angle(1, 90.0)
        self.servo.set_angle(0, 90.0)

    def update_target(self, obj_cx, obj_cy) -> bool:
        current_time = time.time()
        dt = current_time - self.last_update
        self.last_target_time = current_time # Actualiza el tiempo del dron detectado
        
        error_x = obj_cx - self.CENTER_X
        error_y = obj_cy - self.CENTER_Y
        
        mover = False

        # --- Control PID (PAN) ---
        if abs(error_x) > self.deadzone:
            if dt > 0:
                P_out_x = self.Kp_pan * error_x
                self.integral_x += error_x * dt
                self.integral_x = max(-self.max_integral, min(self.max_integral, self.integral_x))
                I_out_x = self.Ki_pan * self.integral_x
                D_out_x = self.Kd_pan * ((error_x - self.prev_error_x) / dt)
                
                pid_output_x = P_out_x + I_out_x + D_out_x
                pid_output_x = max(-3.0, min(3.0, pid_output_x)) # Limita el salto máximo
                self.pan_angle += pid_output_x
                self.pan_angle = max(0.0, min(180.0, self.pan_angle))

            mover = True
        else:
            self.integral_x = 0.0

        self.prev_error_x = error_x

        # --- Control PID (TILT) ---
        if abs(error_y) > self.deadzone:
            if dt > 0:
                P_out_y = self.Kp_tilt * error_y
                self.integral_y += error_y * dt
                self.integral_y = max(-self.max_integral, min(self.max_integral, self.integral_y))
                I_out_y = self.Ki_tilt * self.integral_y
                D_out_y = self.Kd_tilt * ((error_y - self.prev_error_y) / dt)
                
                pid_output_y = P_out_y + I_out_y + D_out_y
                pid_output_y = max(-2.0, min(2.0, pid_output_y))
                self.tilt_angle += pid_output_y
                
                # Restricción estricta de Tilt entre 45 y 135
                self.tilt_angle = max(45.0, min(135.0, self.tilt_angle))

            mover = True
        else:
            self.integral_y = 0.0

        self.prev_error_y = error_y

        if mover and dt > self.update_rate:
            self.servo.set_angle(1, 180.0 - self.pan_angle)
            self.servo.set_angle(0, 180.0 - self.tilt_angle)
            self.last_update = current_time

        return True

    def reset_target(self):
        """Se llama cuando el cliente manda el comando LOST."""
        self.integral_x = 0.0
        self.integral_y = 0.0
        self.prev_error_x = 0.0
        self.prev_error_y = 0.0
        # Forzar entrada al modo escaneo de inmediato
        self.last_target_time = 0 
        return True

    def idle_sweep(self):
        """Modo de búsqueda: Tilt a 70 grados, Paneo continuo."""
        self.tilt_angle = 70.0
        
        self.pan_angle += self.pan_sweep_speed * self.pan_sweep_dir
        if self.pan_angle >= 180.0:
            self.pan_angle = 180.0
            self.pan_sweep_dir = -1
        elif self.pan_angle <= 0.0:
            self.pan_angle = 0.0
            self.pan_sweep_dir = 1

        self.servo.set_angle(1, 180.0 - self.pan_angle)
        self.servo.set_angle(0, 180.0 - self.tilt_angle)


# --- Servidor UDP ---
class ControlServer(threading.Thread):
    def __init__(self, host, port, servo_controller, tracker):
        super().__init__(daemon=True)
        self.host = host
        self.port = port
        self.servo = servo_controller
        self.tracker = tracker
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
        parts = msg.upper().split()
        if not parts:
            return False

        if parts[0] == "SERVO":
            if len(parts) < 3:
                return False
            try:
                channel = int(parts[1])
                angle = float(parts[2])
            except ValueError:
                return False
            return self.servo.set_angle(channel, angle)
            
        elif parts[0] in ("TARGET", "COORD"):
            if len(parts) < 3:
                return False
            try:
                cx = float(parts[1])
                cy = float(parts[2])
            except ValueError:
                return False
            return self.tracker.update_target(cx, cy)
            
        elif parts[0] == "LOST":
            return self.tracker.reset_target()
        else:
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
    tracker = ServoTracker(servo_ctrl)

    try:
        control_server = ControlServer(CONTROL_HOST, CONTROL_PORT, servo_ctrl, tracker)
        control_server.start()

        stream_process = start_stream()

        print("\n=== Sistema Listo (PID Local en RPi) ===")
        print("Esperando comandos UDP ('TARGET cx cy' o 'SERVO chan angle')")
        print("Presiona Ctrl+C para salir.")

        while True:
            # Reducimos el sleep para que el escaneo sea fluido
            time.sleep(0.05) 
            
            # Si pasa 1 segundo sin actualizaciones del dron (o se manda LOST), entra en escaneo
            if time.time() - tracker.last_target_time > 1.0:
                tracker.idle_sweep()

    except KeyboardInterrupt:
        pass

    finally:
        if stream_process and stream_process.poll() is None:
            stop_stream(stream_process)

        if control_server:
            control_server.stop()
            control_server.join(timeout=2)
        
        for i in range(16):
            servo_ctrl.disable(i)

    print("Programa finalizado.")