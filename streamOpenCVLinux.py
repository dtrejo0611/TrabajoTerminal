import cv2

# Pipeline GStreamer ajustada para trabajar con OpenCV

pipeline = (
    "udpsrc port=5000 caps=\"application/x-rtp, media=video, clock-rate=90000, encoding-name=H264, payload=96\" "
    "! rtph264depay ! h264parse ! nvv4l2decoder ! nvvidconv ! videoconvert "
    "! video/x-raw, format=BGR "
    "! appsink sync=false max-buffers=1 drop=true"
)

print("Iniciando VideoCapture con pipeline:")
print(pipeline)
cap = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)

if not cap.isOpened():
    print("No se pudo abrir el stream. Revisa la pipeline y que haya video entrante.")
    exit(1)

print("Stream iniciado correctamente. Presiona 'q' para salir.")
while True:
    ret, frame = cap.read()
    if not ret:
        print("No se recibió ningún frame. Esperando...")
        continue
    cv2.imshow('Stream Jetson OpenCV', frame)
    key = cv2.waitKey(1)
    if key == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()
print("Stream cerrado.")