import subprocess
import shlex
import time

# --- Configuración del Stream ---
RPI_IP_CLIENTE = "192.168.1.131"  # IP de tu laptop/PC
PORT = "5000"
BITRATE = "2000000"

# El comando completo que ejecuta la transmisión
# rpicam-vid y GStreamer están concatenados con pipe (|)
STREAM_COMMAND = (
    f"rpicam-vid -t 0 --width 1280 --height 720 --framerate 30 --codec h264 --inline --bitrate {BITRATE} -o - | "
    f"gst-launch-1.0 -v fdsrc ! h264parse ! rtph264pay config-interval=1 pt=96 ! udpsink host={RPI_IP_CLIENTE} port={PORT} sync=false"
)

def start_stream():
    """Inicia la tubería de streaming como un proceso secundario."""
    print("🎬 Iniciando streaming de cámara...")
    
    # Usamos shell=True para ejecutar toda la tubería como un solo comando de shell
    # Esto es necesario debido al uso del pipe (|) entre rpicam-vid y gst-launch-1.0
    process = subprocess.Popen(
        STREAM_COMMAND, 
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    print(f"✅ Streaming iniciado. PID: {process.pid}")
    return process

def stop_stream(process):
    """Detiene el proceso de streaming."""
    print("\n🛑 Deteniendo streaming...")
    
    # En sistemas Linux (como Raspberry Pi OS), es mejor usar un grupo de procesos
    # para asegurar que tanto rpicam-vid como gst-launch-1.0 se detengan.
    try:
        # Envía una señal de terminación (SIGTERM) al grupo de procesos
        # Esto mata la cadena de comandos (rpicam-vid | gst-launch-1.0)
        subprocess.run(f"pkill -TERM -P {process.pid}", shell=True, check=True)
        print("✅ Streaming detenido correctamente.")
    except Exception as e:
        print(f"⚠️ Error al detener el proceso. Intentando kill simple: {e}")
        # En caso de que pkill falle (o si shell=True causa problemas), 
        # se detiene el proceso principal.
        process.terminate()
        process.wait()
        print("✅ Streaming detenido (por terminate).")


if __name__ == "__main__":
    stream_process = None
    try:
        stream_process = start_stream()
        
        # Bucle principal para simular el trabajo con los motores
        print("\n⚙️  El sistema está listo para controlar motores o realizar otras tareas.")
        print("   Presiona Ctrl+C para detener el streaming y el script.")
        
        while True:
            # Aquí va tu código para controlar motores o tareas del CM4
            # Ejemplo: time.sleep(1)
            time.sleep(1) 
            
    except KeyboardInterrupt:
        # Captura Ctrl+C
        pass
    finally:
        # Asegura que el stream se detenga al finalizar
        if stream_process and stream_process.poll() is None:
            stop_stream(stream_process)

    print("Programa finalizado.")