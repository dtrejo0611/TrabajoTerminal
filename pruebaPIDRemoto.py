import cv2
import threading
import socket
import sys
import time
from ultralytics import YOLO

ejecutando = True

# --- 1. FUNCIONES DE COMUNICACIÓN UDP ---
def send_control_command(server_ip: str, server_port: int, message: str, timeout=0.5, verbose=True) -> bool:
    """Envía las coordenadas del dron u otros comandos simples vía UDP."""
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
    """Bucle en segundo plano para comandos manuales opcionales por consola."""
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

# --- 2. HILO PRINCIPAL: VISIÓN Y ENVÍO DE COORDENADAS ---
if __name__ == "__main__":
    RPI_SERVER_IP = "192.168.8.224" 
    RPI_CONTROL_PORT = 6000

    hilo_control = threading.Thread(target=interactive_command_loop, args=(RPI_SERVER_IP, RPI_CONTROL_PORT), daemon=True)
    hilo_control.start()

    print("Cargando modelo TensorRT...")
    try:
        modelo = YOLO("dron_1camara.engine", task="detect")
    except Exception as e:
        print(f"Error al cargar el modelo: {e}")
        sys.exit()

    FRAME_W, FRAME_H = 640, 360
    CENTER_X, CENTER_Y = FRAME_W / 2, FRAME_H / 2

    print("Centrando servos de la RPi al iniciar...")
    send_control_command(RPI_SERVER_IP, RPI_CONTROL_PORT, "SERVO 1 90.0")
    send_control_command(RPI_SERVER_IP, RPI_CONTROL_PORT, "SERVO 0 90.0")
    time.sleep(0.5)

    pipeline = (
        "udpsrc port=5001 ! application/x-rtp, encoding-name=H264, payload=96 ! "
        "rtpjitterbuffer latency=200 ! "
        "rtph264depay ! h264parse ! nvv4l2decoder ! nvvidconv ! "
        "video/x-raw, width=640, height=360 ! videoconvert ! video/x-raw, format=BGR ! "
        "appsink sync=false drop=true max-buffers=1"
    )

    cap = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)
    if not cap.isOpened():
        print("❌ Error de GStreamer.")
        ejecutando = False

    print("✅ Iniciando detección y envío de coordenadas. Presiona 'q' en la ventana para salir.")

    while ejecutando:
        capturaOK, frame = cap.read()
        if not capturaOK: break

        resultados = modelo(frame, stream=True, verbose=False, imgsz=640, half=True)
        target_encontrado = False

        for r in resultados:
            frame_anotado = r.plot()
            boxes = r.boxes.xyxy.cpu().numpy() # [x1, y1, x2, y2]
            
            if len(boxes) > 0:
                # Tomamos la primera detección
                box = boxes[0]
                obj_cx = (box[0] + box[2]) / 2
                obj_cy = (box[1] + box[3]) / 2
                
                # Dibujar guías visuales locales
                cv2.circle(frame_anotado, (int(obj_cx), int(obj_cy)), 5, (0, 0, 255), -1)
                cv2.circle(frame_anotado, (int(CENTER_X), int(CENTER_Y)), 5, (0, 255, 0), -1)
                
                # Enviar unicamente las coordenadas del centro a la Raspberry Pi
                send_control_command(RPI_SERVER_IP, RPI_CONTROL_PORT, f"TARGET {obj_cx:.1f} {obj_cy:.1f}", verbose=False)
                target_encontrado = True

        if not target_encontrado:
            send_control_command(RPI_SERVER_IP, RPI_CONTROL_PORT, "LOST", verbose=False)

        cv2.imshow("Tracking Dron - YOLOv8 (Cliente)", frame_anotado)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            ejecutando = False
            print("\nSaliendo...")
            break

    cap.release()
    cv2.destroyAllWindows()
    sys.exit()
