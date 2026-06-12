import cv2
import threading
import numpy as np
import time
from ultralytics import YOLO

# Cargar el modelo de BATCH FIJO 3
print("Cargando modelo Batch=3...")
try:
    modelo = YOLO("dron.engine", task="detect")
except:
    print("Error cargando engine. Asegúrate de haber corrido exportar_fijo.py")
    exit()

# Pipeline GStreamer (Igual que antes)
def gstreamer_pipeline(port):
    return (
        f"udpsrc port={port} ! "
        "application/x-rtp, encoding-name=H264, payload=96 ! "
        "rtph264depay ! h264parse ! "
        "nvv4l2decoder ! nvvidconv ! "
        "video/x-raw, width=640, height=360 ! "
        "videoconvert ! video/x-raw, format=BGR ! "
        "appsink sync=false drop=true max-buffers=1"
    )

class CameraStream:
    def __init__(self, port):
        self.port = port
        self.cap = cv2.VideoCapture(gstreamer_pipeline(port), cv2.CAP_GSTREAMER)
        self.grabbed, self.frame = self.cap.read()
        self.stopped = False
        self.lock = threading.Lock()
        
        # Frame negro de respaldo por si falla la cámara
        self.black_frame = np.zeros((360, 640, 3), dtype=np.uint8)

        if not self.cap.isOpened():
            print(f"Advertencia: Cámara en puerto {port} no abrió.")

        self.t = threading.Thread(target=self.update, args=())
        self.t.daemon = True
        self.t.start()

    def update(self):
        while not self.stopped:
            if not self.cap.isOpened():
                time.sleep(0.1)
                continue
            grabbed, frame = self.cap.read()
            if grabbed:
                with self.lock:
                    self.grabbed = grabbed
                    self.frame = frame
            else:
                # Si perdemos señal, mantenemos el último frame o negro
                pass

    def read(self):
        with self.lock:
            # Si no hay frame capturado, devolvemos uno negro para no romper el Batch=3
            if self.frame is None:
                return False, self.black_frame
            return self.grabbed, self.frame

    def stop(self):
        self.stopped = True
        self.t.join()
        self.cap.release()

# --- INICIO ---
cam1 = CameraStream(5000)
cam2 = CameraStream(5001)
cam3 = CameraStream(5002)

print("Esperando estabilización...")
time.sleep(2)

print("Iniciando. Presiona 'q' para salir.")

while True:
    # 1. Leemos las 3 cámaras
    # IMPORTANTE: Ahora siempre necesitamos 3 variables, aunque sean frames negros
    _, f1 = cam1.read()
    _, f2 = cam2.read()
    _, f3 = cam3.read()

    # 2. INFERENCIA EN BATCH
    # Al ser batch fijo, pasamos la lista exacta de 3
    # verbose=False quita texto en consola para ganar velocidad
    resultados = modelo([f1, f2, f3], verbose=False, imgsz=640, half=True)

    # 3. MOSTRAR
    # Iteramos sobre los resultados y mostramos
    for i, r in enumerate(resultados):
        frame_anotado = r.plot()
        cv2.imshow(f"Camara {i+1}", frame_anotado)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cam1.stop()
cam2.stop()
cam3.stop()
cv2.destroyAllWindows()
