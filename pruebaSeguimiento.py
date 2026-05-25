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

    # Parámetros de Tracking (¡Aquí es donde tendrás que afinar!)
    FRAME_W, FRAME_H = 640, 360
    CENTER_X, CENTER_Y = FRAME_W / 2, FRAME_H / 2
    
    pan_angle = 90.0  # Servo 1 (Centro)
    tilt_angle = 90.0 # Servo 0 (Centro)

    print("Moviendo servos a la posición inicial (90°)...")
    send_control_command(RPI_SERVER_IP, RPI_CONTROL_PORT, "SERVO 1 90.0")
    send_control_command(RPI_SERVER_IP, RPI_CONTROL_PORT, "SERVO 0 90.0")
    time.sleep(0.5) # Le damos medio segundo para que lleguen físicamente a la posición
    # -----------------
    
    # Constantes Control Proporcional (PAN)
    Kp_pan = 0.01
    
    # Constantes Control PID (TILT)
    Kp_tilt = 8    # Proporcional: Fuerza de reacción inmediata
    Ki_tilt = 5   # Integral: Corrige el error a largo plazo
    Kd_tilt = 0.1   # Derivativo: Amortigua el movimiento (evita oscilaciones)
    
    # Variables de estado para el PID del Tilt
    prev_error_y = 0.0
    integral_y = 0.0
    max_integral = 500.0 # Anti-windup: Límite para evitar que la integral crezca infinito
    
    deadzone = 60 # Zona muerta en píxeles.
    
    last_servo_update = time.time()
    servo_update_rate = 0.1 # Enviar comandos máximo cada 0.1 segundos (10 Hz)

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
            boxes = r.boxes.xyxy.cpu().numpy() # Formato: [x1, y1, x2, y2]
            
            if len(boxes) > 0:
                # Tomamos la primera detección (puedes agregar lógica para elegir la de mayor confianza)
                box = boxes[0]
                obj_cx = (box[0] + box[2]) / 2
                obj_cy = (box[1] + box[3]) / 2
                
                # Dibujar un punto en el centro del objeto detectado y en el centro de la pantalla
                cv2.circle(frame_anotado, (int(obj_cx), int(obj_cy)), 5, (0, 0, 255), -1)
                cv2.circle(frame_anotado, (int(CENTER_X), int(CENTER_Y)), 5, (0, 255, 0), -1)
                
                # Calcular el error (distancia al centro)
                error_x = obj_cx - CENTER_X
                error_y = obj_cy - CENTER_Y
                
                current_time = time.time()
                dt = current_time - last_servo_update
                
                # Actualizar servos si ha pasado suficiente tiempo
                if dt > servo_update_rate:
                    mover = False
                    
                    # --- CONTROL P (PAN - Izquierda / Derecha) ---
                    if abs(error_x) > deadzone:
                        pan_angle += error_x * Kp_pan
                        pan_angle = max(0.0, min(180.0, pan_angle))
                        pan_angle_enviar = 180 - pan_angle
                        mover = True
                        
                    # --- CONTROL PID (TILT - Arriba / Abajo) ---
                    if abs(error_y) > deadzone:
                        # 1. Proporcional
                        P_out = Kp_tilt * error_y
                        
                        # 2. Integral (con Anti-Windup)
                        integral_y += error_y * dt
                        integral_y = max(-max_integral, min(max_integral, integral_y)) # Limitar
                        I_out = Ki_tilt * integral_y
                        
                        # 3. Derivativo
                        D_out = Kd_tilt * ((error_y - prev_error_y) / dt) if dt > 0 else 0.0
                        
                        # Salida Total PID
                        pid_output_y = P_out + I_out + D_out
                        
                        # Aplicar al ángulo
                        tilt_angle += pid_output_y
                        tilt_angle = max(0.0, min(180.0, tilt_angle))
                        
                        # Mapeo de inversión (si estaba en tu código original)
                        tilt_angle_envio = 180.0 - tilt_angle 
                        mover = True
                    else:
                        # Si está en la zona muerta, resetear la integral para no acumular memoria fantasma
                        integral_y = 0.0
                        tilt_angle_envio = 180.0 - tilt_angle
                    
                    # Actualizar error anterior para el próximo ciclo
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
