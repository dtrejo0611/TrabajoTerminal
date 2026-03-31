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
    
    # Constante Proporcional (Convierte píxeles de error a grados). 
    # Si el tracking es muy lento, súbelo (ej. 0.08). Si oscila mucho, bájalo (ej. 0.02).
    Kp_pan = 0.05  
    Kp_tilt = 0.05 
    
    deadzone = 40 # Zona muerta en píxeles. Si el dron está dentro de este radio del centro, no se mueve.
    
    last_servo_update = time.time()
    servo_update_rate = 0.1 # Enviar comandos máximo cada 0.1 segundos (10 Hz)

    pipeline = (
        "udpsrc port=5002 ! application/x-rtp, encoding-name=H264, payload=96 ! "
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
                
                # Actualizar servos si ha pasado suficiente tiempo
                if time.time() - last_servo_update > servo_update_rate:
                    mover = False
                    
                    # PAN (Izquierda / Derecha) -> Servo 1
                    if abs(error_x) > deadzone:
                        pan_angle += error_x * Kp_pan
                        pan_angle = max(0.0, min(180.0, pan_angle)) # Limitar entre 0 y 180
                        mover = True
                        
                    # TILT (Arriba / Abajo) -> Servo 0
                    if abs(error_y) > deadzone:
                        tilt_angle += error_y * Kp_tilt
                        tilt_angle = max(0.0, min(180.0, tilt_angle)) # Limitar entre 0 y 180
                        mover = True
                    
                    if mover:
                        # NOTA: Dependiendo de cómo estén montados tus servos, 
                        # podrías necesitar invertir la dirección. Si el servo se aleja 
                        # en vez de acercarse, cambia += por -= en la línea del ángulo.
                        send_control_command(RPI_SERVER_IP, RPI_CONTROL_PORT, f"SERVO 1 {pan_angle:.1f}", verbose=False)
                        send_control_command(RPI_SERVER_IP, RPI_CONTROL_PORT, f"SERVO 0 {tilt_angle:.1f}", verbose=False)
                        last_servo_update = time.time()

            cv2.imshow("Tracking Dron - YOLOv8", frame_anotado)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            ejecutando = False
            print("\nSaliendo... Presiona ENTER en la consola.")
            break

    cap.release()
    cv2.destroyAllWindows()
    sys.exit()
