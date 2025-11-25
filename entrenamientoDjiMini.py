from ultralytics import YOLO

if __name__ == "__main__":
    # Cargamos el modelo Small (buen balance para la Jetson Orin Nano)
    modelo = YOLO("yolov8s.pt")

    # Entrenamiento optimizado
    modelo.train(
        data="./datasets/djimini/data.yaml",
        epochs=150,           # Subimos a 150, el Early Stopping lo parará si acaba antes
        patience=30,          # Si no mejora en 30 épocas, se detiene solo
        batch=16,             # 16 es seguro para la RTX 4050 con el modelo 's'
        imgsz=640,            # Tamaño estándar. Si el drone es muy pequeño, podrías probar 960
        device=0,             # Asegura que use tu GPU NVIDIA
        workers=0,            # Núcleos de CPU para cargar datos
        pretrained=True,      # Correcto
        cache=True,           # ACELERA MUCHO: carga las 1000 fotos en RAM
        project="Dron_Detection", # Nombre de la carpeta de salida para orden
        name="entrenamiento_v1"
    )