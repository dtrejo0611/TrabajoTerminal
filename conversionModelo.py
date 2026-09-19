from ultralytics import YOLO
import gc
import torch

# Limpieza
gc.collect()
if torch.cuda.is_available():
    torch.cuda.empty_cache()

print("Cargando modelo...")
model = YOLO("dron.pt")

print("Generando Engine con BATCH FIJO = 3...")
# Al poner dynamic=False y batch=3, "cableamos" el modelo.
# Es mucho más estable para la Jetson.
model.export(
    format="engine",
    batch=3,        # <--- OBLIGATORIO: Siempre procesará 3 de golpe
    dynamic=False,  # <--- Apagamos el modo dinámico
    half=True,      # FP16
    workspace=0.5,  # Memoria baja para que no falle la exportación
    simplify=True
)

print("¡Listo! Nuevo 'dron.engine' creado para 3 cámaras.")
