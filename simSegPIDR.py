import cv2
import threading
import socket
import sys
import time
from ultralytics import YOLO

ejecutando = True

# --- VARIABLES GLOBALES PARA SIMULACIÓN ---
use_simulation = False
sim_cx = 320.0  # Centro X por defecto (resolución 640x360)
sim_cy = 180.0  # Centro Y por defecto

# --- 1. FUNCIONES DE CONTROL UDP ---
def send_control_command(server_ip: str, server_port: int, message: str, timeout=0.5, verbose=True) -> bool:
    """Envía un comando UDP simple al servidor."""
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
    """Bucle en segundo plano para comandos manuales y de simulación."""
    global ejecutando, use_simulation, sim_cx, sim_cy
    
    print("\n🎮 CONTROL MANUAL Y SIMULACIÓN DISPONIBLE")
    print("  - 'quit' o 'exit' para salir")
    print("  - 'servo <canal> <angulo>' para control directo (ej: servo 1 90)")
    print("  - 'sim <x> <y>' para simular coordenadas de destino en la RPi (ej: sim 100 200)")
    print("  - 'sim off' para volver al rastreo automático con YOLO\n")
    
    try:
        while ejecutando:
            cmd = input().strip()
            if not cmd: continue
            
            if cmd.lower() in ("quit", "exit"):
                print("⏳ Cerrando sistema...")
                ejecutando = False
                break
                
            parts = cmd.split()
            
            # Comando SIMULACIÓN DE COORDENADAS
            if parts[0].lower() == "sim":
                if len(parts) == 2 and parts[1].lower() == "off":
                    use_simulation = False
                    print("👁️ Simulación desactivada. Rastreo por YOLO reanudado.")
                elif len(parts) == 3:
                    try:
                        sim_cx = float(parts[1])
                        sim_cy = float(parts[2])
                        use_simulation = True
                        print(f"🎯 Simulación activa: Enviando coordenada X={sim_cx}, Y={sim_cy} a la RPi")
                    except ValueError:
                        print("⚠️ Error: Las coordenadas deben ser numéricas.")
                else:
                    print("⚠️ Uso: sim <x> <y> o sim off")
                    
            # Comando SERVO directo
            elif parts[0].lower() == "servo" and len(parts) == 3:
                try:
                    channel = int(parts[1])
                    angle = float(parts[2])
                    msg = f"SERVO {channel} {angle}"
                    ok = send_control_command(server_ip, server_port, msg)
                    print("✅ ACK" if ok else "❌ NO ACK")
                except ValueError:
                    print("⚠️ Error de formato. Uso: servo <canal> <angulo>")
    except KeyboardInterrupt:
        ejecutando = False

# --- 2. HILO PRINCIPAL: VISIÓN Y ENVÍO DE COORDENADAS ---
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

    FRAME_W, FRAME_H = 640,	 360
    CENTER_X, CENTER_Y = FRAME_W / 2, FRAME_H / 2

    pipeline = (
        "udpsrc port=5003 ! application/x-rtp, encoding-name=H264, payload=96 ! "
        "rtpjitterbuffer latency=200 ! "
        "rtph264depay ! h264parse ! nvv4l2decoder ! nvvidconv ! "
        "video/x-raw, width=640, height=360 ! videoconvert ! video/x-raw, format=BGR ! "
        "appsink sync=false drop=true max-buffers=1"
    )

    cap = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)
    if not cap.isOpened():
        print("❌ Error de GStreamer.")
        ejecutando = False

    print("✅ Iniciando envío de coordenadas. Presiona 'q' en la ventana de video para salir.")

    while ejecutando:
        capturaOK, frame = cap.read()
        if not capturaOK: break

        resultados = modelo(frame, stream=True, verbose=False, imgsz=640, half=True)
        target_encontrado = False

        for r in resultados:
            frame_anotado = r.plot()
            
            obj_cx = None
            obj_cy = None
            
            if use_simulation:
                # 1. Modo Simulación (Inyecta coordenadas manuales desde la consola)
                obj_cx = sim_cx
                obj_cy = sim_cy
                
                cv2.circle(frame_anotado, (int(obj_cx), int(obj_cy)), 8, (255, 0, 0), -1)
                cv2.putText(frame_anotado, f"SIM COORD: {obj_cx},{obj_cy}", (10, 30), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 0, 0), 2)
            else:
                # 2. Modo Normal (Detección por YOLO)
                boxes = r.boxes.xyxy.cpu().numpy()
                if len(boxes) > 0:
                    box = boxes[0]
                    obj_cx = (box[0] + box[2]) / 2
                    obj_cy = (box[1] + box[3]) / 2
                    
                    cv2.circle(frame_anotado, (int(obj_cx), int(obj_cy)), 5, (0, 0, 255), -1)
            
            # Centro visual de referencia (Verde)
            cv2.circle(frame_anotado, (int(CENTER_X), int(CENTER_Y)), 5, (0, 255, 0), -1)
            
            # Envío de coordenadas a la RPi para que ella resuelva el PID localmente
            if obj_cx is not None and obj_cy is not None:
                send_control_command(RPI_SERVER_IP, RPI_CONTROL_PORT, f"TARGET {obj_cx:.1f} {obj_cy:.1f}", verbose=False)
                target_encontrado = True

        if not target_encontrado and not use_simulation:
            send_control_command(RPI_SERVER_IP, RPI_CONTROL_PORT, "LOST", verbose=False)

        cv2.imshow("Tracking Dron - YOLOv8 (Cliente Emisor)", frame_anotado)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            ejecutando = False
            print("\nSaliendo...")
            break

    cap.release()
    cv2.destroyAllWindows()
    sys.exit()
