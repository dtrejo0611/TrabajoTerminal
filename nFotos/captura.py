import cv2
import threading
import socket
import sys
import time
import os

ejecutando = True

# --- CONFIGURACIÓN DE DATASET ---
save_dir = "dataset_drones"
os.makedirs(save_dir, exist_ok=True)
trigger_photo = False # Bandera para tomar foto desde la consola

# --- 1. FUNCIONES DE CONTROL UDP ---
def send_control_command(server_ip: str, server_port: int, message: str, timeout=0.5, verbose=True) -> bool:
    """Envía el comando UDP a la CM4 para mover los servos."""
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
    """Bucle en segundo plano para posicionar la cámara y capturar fotos."""
    global ejecutando, trigger_photo
    
    print("\n🎮 CONTROL MANUAL PARA DATASET")
    print("  - 'quit' o 'exit' para salir")
    print("  - 'servo <canal> <angulo>' para mover cámara (ej: servo 1 90)")
    print("  - 'foto' para capturar una imagen desde la consola\n")
    
    try:
        while ejecutando:
            cmd = input().strip()
            if not cmd: continue
            
            if cmd.lower() in ("quit", "exit"):
                print("⏳ Cerrando sistema...")
                ejecutando = False
                break
                
            elif cmd.lower() == "foto":
                trigger_photo = True
                continue

            parts = cmd.split()
            
            # Comando SERVO
            if parts[0].lower() == "servo" and len(parts) == 3:
                try:
                    channel = int(parts[1])
                    angle = float(parts[2])
                    msg = f"SERVO {channel} {angle}"
                    ok = send_control_command(server_ip, server_port, msg)
                    print("✅ ACK" if ok else "❌ NO ACK")
                except ValueError:
                    print("⚠️ Error de formato. Uso: servo <canal> <angulo>")
            else:
                print("⚠️ Comando no reconocido.")
    except KeyboardInterrupt:
        ejecutando = False

# --- 2. HILO PRINCIPAL: VISIÓN Y CAPTURA ---
if __name__ == "__main__":
    RPI_SERVER_IP = "192.168.8.147" 
    RPI_CONTROL_PORT = 6000

    hilo_control = threading.Thread(target=interactive_command_loop, args=(RPI_SERVER_IP, RPI_CONTROL_PORT), daemon=True)
    hilo_control.start()

    print("Moviendo servos a la posición inicial (90° y 45°)...")
    send_control_command(RPI_SERVER_IP, RPI_CONTROL_PORT, "SERVO 1 90.0")
    send_control_command(RPI_SERVER_IP, RPI_CONTROL_PORT, "SERVO 0 45.0")
    time.sleep(0.5)

    # Pipeline configurado para recibir a 2 Mbps
    pipeline = (
        "udpsrc port=5002 ! application/x-rtp, encoding-name=H264, payload=96 ! "
        "rtpjitterbuffer latency=200 ! "
        "rtph264depay ! h264parse ! nvv4l2decoder ! nvvidconv ! "
        "video/x-raw, width=640, height=360 ! videoconvert ! video/x-raw, format=BGR ! "
        "appsink sync=false drop=true max-buffers=1"
    )

    cap = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)
    if not cap.isOpened():
        print("❌ Error de GStreamer. Revisa la transmisión.")
        ejecutando = False

    print("✅ Transmisión iniciada.")
    print("👉 Presiona 'g' en la ventana de video para guardar una foto.")
    print("👉 Presiona 'q' en la ventana de video para salir.")

    while ejecutando:
        capturaOK, frame_original = cap.read()
        if not capturaOK: break

        # Hacemos una copia para mostrar en pantalla con guías (sin afectar la foto guardada)
        frame_visual = frame_original.copy()
        h, w = frame_visual.shape[:2]
        
        # Dibujar una cruz verde central para facilitar el encuadre del dron
        cv2.drawMarker(frame_visual, (w//2, h//2), (0, 255, 0), cv2.MARKER_CROSS, 20, 1)

        cv2.imshow("Recoleccion - Presiona 'g' para foto", frame_visual)

        key = cv2.waitKey(1) & 0xFF

        # Guardar foto si se presiona 'g' en la ventana de video, o si se escribió 'foto' en consola
        if key == ord('g') or trigger_photo:
            timestamp = int(time.time() * 1000)
            filename = os.path.join(save_dir, f"dron_{timestamp}.jpg")
            
            # Guardamos el frame_original para que la cruz verde no aparezca en el dataset
            cv2.imwrite(filename, frame_original)
            print(f"📸 Guardado: {filename}")
            trigger_photo = False # Reseteamos la bandera

        elif key == ord('q'):
            ejecutando = False
            print("\nSaliendo... Presiona ENTER en la consola.")
            break

    cap.release()
    cv2.destroyAllWindows()
    sys.exit()
