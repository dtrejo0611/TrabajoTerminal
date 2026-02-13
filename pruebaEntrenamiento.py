from ultralytics import YOLO
import cv2

# 1. CARGAMOS EL MODELO OPTIMIZADO (.engine)
# Asegúrate de haber hecho el paso de exportación primero.
try:
    print("Cargando modelo TensorRT...")
    modelo = YOLO("dron.engine", task="detect")
except:
    print("No se encontró .engine, cargando .pt (será más lento)")
    modelo = YOLO("dron.pt")

# 2. PIPELINE AJUSTADA (Con max-buffers=1)
pipeline = (
    "udpsrc port=5002 ! "
    "application/x-rtp, encoding-name=H264, payload=96 ! "
    "rtph264depay ! h264parse ! nvv4l2decoder ! "
    "nvvidconv ! "
    "video/x-raw, width=640, height=360 ! "
    "videoconvert ! "
    "video/x-raw, format=BGR ! "
    # max-buffers=1 es VITAL para evitar lag en tiempo real
    "appsink sync=false drop=true max-buffers=1"
)

cap = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)

if not cap.isOpened():
    print("Error al abrir pipeline")
    exit()

print("Iniciando detección. Presiona 'q' para salir.")

while True:
    capturaOK, frame = cap.read()
    if not capturaOK:
        print("Frame no recibido")
        break

    # 3. INFERENCIA
    # imgsz=640 optimiza el tamaño de entrada
    # half=True usa FP16 (más rápido en Jetson)
    resultados = modelo(frame, stream=True, verbose=False, imgsz=640, half=True)

    for r in resultados:
        # 4. VISUALIZACIÓN RÁPIDA
        # plot() es C++ optimizado, mucho más rápido que dibujar manual con cv2.rectangle
        frame_anotado = r.plot()

        # Si de verdad necesitas dibujar manual, descomenta tu código anterior,
        # pero plot() es preferible para rendimiento.

    cv2.imshow("Resultados", frame_anotado)

    # WaitKey(1) es suficiente
    if cv2.waitKey(1) == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()