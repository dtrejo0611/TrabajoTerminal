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

# Función para generar el pipeline cambiando solo el puerto
def gstreamer_pipeline(port):
    return (
        f"udpsrc port={port} ! "
        "application/x-rtp, encoding-name=H264, payload=96 ! "
        "rtph264depay ! h264parse ! nvv4l2decoder ! "
        "nvvidconv ! "
        "video/x-raw, width=640, height=360 ! "
        "videoconvert ! "
        "video/x-raw, format=BGR ! "
        "appsink sync=false drop=true max-buffers=1"
    )


print("Inicializando streams de GStreamer...")

# 1. Inicializamos las 3 capturas en puertos distintos
# Asegúrate de que tus emisores (Raspberry Pis, etc.) envíen a estos puertos exactos
cap1 = cv2.VideoCapture(gstreamer_pipeline(5000), cv2.CAP_GSTREAMER)
cap2 = cv2.VideoCapture(gstreamer_pipeline(5001), cv2.CAP_GSTREAMER)
cap3 = cv2.VideoCapture(gstreamer_pipeline(5002), cv2.CAP_GSTREAMER)

# Verificación de seguridad
if not cap1.isOpened() or not cap2.isOpened() or not cap3.isOpened():
    print("Advertencia: Alguna de las cámaras no se pudo abrir correctamente.")
    # No hacemos exit() aquí para permitir que las que sí funcionen se muestren,
    # pero revisa la consola por errores de GStreamer.

print("Streams iniciados. Presiona 'q' para salir.")

while True:
    # 2. Leemos los frames de cada cámara
    ret1, frame1 = cap1.read()
    ret2, frame2 = cap2.read()
    ret3, frame3 = cap3.read()

    resultados1 = modelo(frame1, stream=True, verbose=False, imgsz=640, half=True)
    resultados2 = modelo(frame2, stream=True, verbose=False, imgsz=640, half=True)
    resultados3 = modelo(frame3, stream=True, verbose=False, imgsz=640, half=True)

    for r in resultados1:
        # 4. VISUALIZACIÓN RÁPIDA
        # plot() es C++ optimizado, mucho más rápido que dibujar manual con cv2.rectangle
        frame_anotado1 = r.plot()

        # Si de verdad necesitas dibujar manual, descomenta tu código anterior,
        # pero plot() es preferible para rendimiento.

    for r in resultados2:
        # 4. VISUALIZACIÓN RÁPIDA
        # plot() es C++ optimizado, mucho más rápido que dibujar manual con cv2.rectangle
        frame_anotado2 = r.plot()

        # Si de verdad necesitas dibujar manual, descomenta tu código anterior,
        # pero plot() es preferible para rendimiento.

    for r in resultados3:
        # 4. VISUALIZACIÓN RÁPIDA
        # plot() es C++ optimizado, mucho más rápido que dibujar manual con cv2.rectangle
        frame_anotado3 = r.plot()

        # Si de verdad necesitas dibujar manual, descomenta tu código anterior,
        # pero plot() es preferible para rendimiento.

    # 3. Mostramos solo si el frame es válido
    cv2.imshow("Camara 1 (Puerto 5000)", frame_anotado1)

    cv2.imshow("Camara 2 (Puerto 5001)", frame_anotado2)

    cv2.imshow("Camara 3 (Puerto 5002)", frame_anotado3)

    # Salida con 'q'
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

# Liberar recursos
cap1.release()
cap2.release()
cap3.release()
cv2.destroyAllWindows()