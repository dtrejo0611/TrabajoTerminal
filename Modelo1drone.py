from ultralytics import YOLO
import gc
import torch
import shutil  # <--- Para copiar archivos
import os

# Limpieza
gc.collect()
if torch.cuda.is_available():
    torch.cuda.empty_cache()

print("Preparando archivos...")
# 1. Hacemos una copia del modelo original .pt con el nombre que queremos para el engine
modelo_original = "dron.pt"
modelo_copia = "dron_1camara.pt"

shutil.copy(modelo_original, modelo_copia)

print("Cargando modelo copiado...")
# 2. Cargamos la copia. Así Ultralytics generará automáticamente "dron_1camara.engine"
model = YOLO(modelo_copia)

print("Generando Engine con BATCH FIJO = 1...")
model.export(
    format="engine",
    batch=1,        
    dynamic=False,  
    half=True,      
    workspace=0.5,  
    simplify=True
)

# 3. (Opcional) Borramos la copia del .pt para mantener la carpeta limpia
if os.path.exists(modelo_copia):
    os.remove(modelo_copia)

print("¡Listo! Se creó 'dron_1camara.engine' y tu 'dron.engine' de 3 cámaras sigue intacto.")
