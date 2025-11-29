from ultralytics import YOLO

# Carga tu modelo
model = YOLO("dron.pt")

# Exporta a formato TensorRT (creará un archivo dron.engine)
# half=True usa precisión de 16 bits (doble de rápido, misma precisión prácticamente)
model.export(format="engine", half=True, device=0)