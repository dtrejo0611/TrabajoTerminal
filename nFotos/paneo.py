import cv2
import threading
import socket
import sys
import time
import os

ejecutando = True
en_paneo = False
trigger_photo = False

# --- CONFIGURACIÓN DE DATASET ---
save_dir = "dataset_drones"
os.makedirs(save_dir, exist_ok=True)

# --- FUNCIONES DE CONTROL UDP ---
def send_control_command(server_ip: str, server_port: int, message: str, timeout=0.5, verbose=True) -> bool:
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

# --- RUTINA DE PANEO ---
def rutina_paneo(server_ip: str, server_port: int):
    """Ejecuta el barrido del servo 1 mientras toma fotos automáticamente."""
    global trigger_photo, en_paneo
    en_paneo = True
    
    print("\n🚀 Iniciando rutina de paneo automático...")
    
    # 1. Fijar Tilt (Servo 0) y llevar Pan (Servo 1) al inicio
    send_control_command(server_ip, server_port, "SERVO 0 140.0")
    send_control_command(server_ip, server_port, "SERVO 1 160.0")
    print("⏳ Esperando a que la cámara llegue a la posición inicial (160°)...")
    time.sleep(2.0) # Tiempo generoso para el recorrido físico largo
    
    # 2. Secuencia de paneo (De 160 a 90, en pasos de 5 grados)
    # Puedes cambiar el '-5' por '-2' si quieres fotos más seguidas
    angulos_pan = range(160, 89, -2) 
    
    for angulo in angulos_pan:
        if not ejecutando: break
        
        # Mover servo
        print(f"🔄 Moviendo a {angulo}°...")
        send_control_command(server_ip, server_port, f"SERVO 1 {float(angulo)}")
        
        # Pausa para estabilización mecánica (evita fotos borrosas)
        time.sleep(0.5) 
        
        # Activar bandera para que el hilo de OpenCV guarde el frame
        trigger_photo = True
        
        # Pequeña pausa para asegurar que OpenCV procese la bandera
        time.sleep(0.1)
        
    print("\n✅ Paneo finalizado. Esperando nuevas instrucciones.")
    en_paneo = False

def interactive_command_loop(server_ip: str, server_port: int):
    global ejecutando
    
    print("\n🎬 CONTROL DE SECUENCIA")
    print("  - Escribe 'paneo' para iniciar la secuencia automática")
    print("  - Escribe 'quit' o 'exit' para salir\n")
    
    try:
        while ejecutando:
            cmd = input().strip().lower()
            if not cmd: continue
            
            if cmd in ("quit", "exit"):
                print("⏳ Cerrando sistema...")
                ejecutando = False
                break
                
            elif cmd == "paneo":
                if not en_paneo:
                    # Lanzamos la rutina en su propio hilo para no bloquear la terminal ni el video
                    threading.Thread(target=rutina_paneo, args=(server_ip, server_port), daemon=True).start()
                else:
                    print("⚠️ Ya hay un paneo en ejecución.")
            else:
                print("⚠️ Comando no reconocido. Usa 'paneo' o 'quit'.")
    except KeyboardInterrupt:
        ejecutando = False

# --- HILO PRINCIPAL: VISIÓN ---
if __name__ == "__main__":
    RPI_SERVER_IP = "192.168.8.147" 
    RPI_CONTROL_PORT = 6000

    hilo_control = threading.Thread(target=interactive_command_loop, args=(RPI_SERVER_IP, RPI_CONTROL_PORT), daemon=True)
    hilo_control.start()

    # Pipeline a 2 Mbps configurado previamente
    pipeline = (
        "udpsrc port=5002 ! application/x-rtp, encoding-name=H264, payload=96 ! "
        "rtpjitterbuffer latency=200 ! "
        "rtph264depay ! h264parse ! nvv4l2decoder ! nvvidconv ! "
        "video/x-raw, width=640, height=360 ! videoconvert ! video/x-raw, format=BGR ! "
        "appsink sync=false drop=true max-buffers=1"
    )

    cap = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)
    if not cap.isOpened():
        print("❌ Error de GStreamer. Revisa la transmisión de la CM4.")
        ejecutando = False

    print("✅ Transmisión iniciada. Esperando comandos.")

    while ejecutando:
        capturaOK, frame = cap.read()
        if not capturaOK: break

        # Mostrar video en vivo
        cv2.imshow("Paneo Automatico Dataset", frame)

        # Si la rutina de paneo activó la bandera, guardamos la foto
        if trigger_photo:
            timestamp = int(time.time() * 1000)
            filename = os.path.join(save_dir, f"dron_pan_{timestamp}.jpg")
            cv2.imwrite(filename, frame)
            print(f"  📸 Foto guardada: {filename}")
            trigger_photo = False # Reiniciar bandera

        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            ejecutando = False
            print("\nSaliendo... Presiona ENTER en la consola.")
            break
            
        elif key == ord('p'):
             if not en_paneo:
                 threading.Thread(target=rutina_paneo, args=(RPI_SERVER_IP, RPI_CONTROL_PORT), daemon=True).start()

    cap.release()
    cv2.destroyAllWindows()
    sys.exit()
