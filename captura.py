#!/usr/bin/env python3
"""
capture_imx477.py
Toma varias fotos con Arducam IMX477 usando Picamera2 y las guarda en /mnt/usbdrive/
"""

import time
from picamera2 import Picamera2

def main():
    picam2 = Picamera2()
    # Configuración para foto fija a 1920x1080
    config = picam2.create_still_configuration(main={"size": (1920, 1080)})
    picam2.configure(config)

    picam2.start()
    time.sleep(1.0)  # Espera para estabilizar exposición y balance de blancos

    for i in range(5):
        if i != 0:
            time.sleep(5.0)  # Espera 5 segundos antes de cada foto, excepto la primera
        archivo = f"/mnt/usbdrive/foto{i}.jpg"
        picam2.capture_file(archivo)
        print("Foto guardada en", archivo)

    picam2.stop()

if __name__ == "__main__":
    main()
