import cv2
import threading
import socket
import sys
import time
from ultralytics import YOLO

ejecutando = True

# --- 1. FUNCIONES DE CONTROL UDP ---
def send_control_command(server_ip: str, server_port: int, message: str, timeout=0.5, verbose=True) -> bool:
    """Envía un comando UDP simple al servidor. verbose=False evita spam en consola para el tracking automático."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(timeout)
        s.sendto(message.encode(), (server_ip, server_port))
        try:
            resp, _ = s.recvfrom(1024)
            return resp.strip().upper() == b"OK"
        except socket.timeout:
            if verbose: print("⚠️ No ack (timeout).")
            return False
        finally:
            s.close()
    except Exception as e:
        if verbose: print(f"❌ Error UDP: {e}")
        return False

def interactive_command_loop(server_ip: str, server_port: int):
    """Bucle en segundo plano para comandos manuales."""
    global ejecutando
    print("\n🎮 CONTROL MANUAL DISPONIBLE (Escribe 'quit' para salir)")
    
    try:
        while ejecutando:
            cmd = input().strip()
            if not cmd: continue
            
            if cmd.lower() in ("quit", "exit"):
                print("⏳ Cerrando sistema...")
                ejecutando = False
                break
                
            parts = cmd.split()
            if parts[0].lower() == "servo" and len(parts) == 3:
                try:
                    channel = int(parts[1])
                    angle = float(parts[2])
                    msg = f"SERVO {channel} {angle}"
                    ok = send_control_command(server_ip, server_port, msg)
                    print("✅ ACK" if ok else "❌ NO ACK")
                except ValueError:
                    print("⚠️ Error de formato.")
    except KeyboardInterrupt:
        ejecutando = False

# --- 2. HILO PRINCIPAL: VISIÓN Y TRACKING ---
if __name__ == "__main__":
    RPI_SERVER_IP = "192.168.8.147" 
    RPI_CONTROL_PORT = 6000

    hilo_control = threading.Thread(target=interactive_command_loop, args=(RPI_SERVER_IP, RPI_CONTROL_PORT), daemon=True)
    hilo_control.start()

    print("Cargando modelo TensorRT...")
    try:
        modelo = YOLO("dron_1camara.engine", task="detect")
    except Exception as e:
        print(f"Error al cargar el modelo: {e}")
        sys.exit()

    # Parámetros de Tracking
    FRAME_W, FRAME_H = 640, 360
    CENTER_X, CENTER_Y = FRAME_W / 2, FRAME_H / 2
    
    pan_angle = 90.0  # Servo 1 (Centro)
    tilt_angle = 45.0 # Servo 0 (Centro)

    print("Moviendo servos a la posición inicial (90°)...")
    send_control_command(RPI_SERVER_IP, RPI_CONTROL_PORT, "SERVO 1 90.0")
    send_control_command(RPI_SERVER_IP, RPI_CONTROL_PORT, "SERVO 0 45.0")
    time.sleep(0.5)
    # -----------------
    
    # Constantes Control PI (PAN)
    Kp_pan = 0.031678  # Tendrás que afinar este valor
    Ki_pan = 0.2577 # Tendrás que afinar este valor
    
    # Constantes Control PID (TILT)
    Kp_tilt = 0.0866269    # Proporcional: Fuerza de reacción inmediata
    Ki_tilt = 0.53953  # Integral: Corrige el error a largo plazo
    Kd_tilt = -0.00975   # Derivativo: Amortigua el movimiento (evita oscilaciones)
    
    # Variables de estado para los controladores
    integral_x = 0.0
    prev_error_y = 0.0
    integral_y = 0.0
    
    max_integral = 500.0 # Anti-windup compartido para X e Y
    deadzone = 20 # Zona muerta en píxeles.
    
    last_servo_update = time.time()
    servo_update_rate = 0.1 # 10 Hz

    pipeline = (
        "udpsrc port=5002 ! application/x-rtp, encoding-name=H264, payload=96 ! "
        "rtpjitterbuffer latency=200 ! "
        "rtph264depay ! h264parse ! nvv4l2decoder ! nvvidconv ! "
        "video/x-raw, width=640, height=360 ! videoconvert ! video/x-raw, format=BGR ! "
        "appsink sync=false drop=true max-buffers=1"
    )

    cap = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)
    if not cap.isOpened():
        print("❌ Error de GStreamer.")
        ejecutando = False

    print("✅ Iniciando Tracking Automático. Presiona 'q' en el video para salir.")

    while ejecutando:
        capturaOK, frame = cap.read()
        if not capturaOK: break

        resultados = modelo(frame, stream=True, verbose=False, imgsz=640, half=True)

        for r in resultados:
            frame_anotado = r.plot()
            
            # --- LÓGICA DE TRACKING ---
            boxes = r.boxes.xyxy.cpu().numpy()
            
            if len(boxes) > 0:
                box = boxes[0]
                obj_cx = (box[0] + box[2]) / 2
                obj_cy = (box[1] + box[3]) / 2
                
                cv2.circle(frame_anotado, (int(obj_cx), int(obj_cy)), 5, (0, 0, 255), -1)
                cv2.circle(frame_anotado, (int(CENTER_X), int(CENTER_Y)), 5, (0, 255, 0), -1)
                
                error_x = obj_cx - CENTER_X
                error_y = obj_cy - CENTER_Y
                
                current_time = time.time()
                dt = current_time - last_servo_update
                
                if dt > servo_update_rate:
                    mover = False
                    
                    # --- CONTROL PI (PAN - Izquierda / Derecha) ---
                    if abs(error_x) > deadzone:
                        # 1. Proporcional
                        P_out_x = Kp_pan * error_x
                        
                        # 2. Integral (con Anti-Windup)
                        integral_x += error_x * dt
                        integral_x = max(-max_integral, min(max_integral, integral_x))
                        I_out_x = Ki_pan * integral_x
                        
                        # Salida Total PI
                        pi_output_x = P_out_x + I_out_x
                        
                        pan_angle += pi_output_x
                        pan_angle = max(0.0, min(180.0, pan_angle))
                        pan_angle_enviar = 180.0 - pan_angle
                        mover = True
                    else:
                        # Resetear integral para no acumular memoria fantasma
                        integral_x = 0.0
                        pan_angle_enviar = 180.0 - pan_angle
                        
                    # --- CONTROL PID (TILT - Arriba / Abajo) ---
                    if abs(error_y) > deadzone:
                        # 1. Proporcional
                        P_out_y = Kp_tilt * error_y
                        
                        # 2. Integral (con Anti-Windup)
                        integral_y += error_y * dt
                        integral_y = max(-max_integral, min(max_integral, integral_y)) 
                        I_out_y = Ki_tilt * integral_y
                        
                        # 3. Derivativo
                        D_out_y = Kd_tilt * ((error_y - prev_error_y) / dt) if dt > 0 else 0.0
                        
                        # Salida Total PID
                        pid_output_y = P_out_y + I_out_y + D_out_y
                        
                        tilt_angle += pid_output_y
                        tilt_angle = max(0.0, min(180.0, tilt_angle))
                        tilt_angle_envio = 180.0 - tilt_angle 
                        mover = True
                    else:
                        integral_y = 0.0
                        tilt_angle_envio = 180.0 - tilt_angle
                    
                    prev_error_y = error_y
                    
                    if mover:
                        send_control_command(RPI_SERVER_IP, RPI_CONTROL_PORT, f"SERVO 1 {pan_angle_enviar:.1f}", verbose=False)
                        send_control_command(RPI_SERVER_IP, RPI_CONTROL_PORT, f"SERVO 0 {tilt_angle_envio:.1f}", verbose=False)
                        last_servo_update = current_time

            cv2.imshow("Tracking Dron - YOLOv8", frame_anotado)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            ejecutando = False
            print("\nSaliendo... Presiona ENTER en la consola.")
            break

    cap.release()
    cv2.destroyAllWindows()
    sys.exit()
