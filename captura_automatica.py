#!/usr/bin/env python3
"""
capture_imx477.py
Toma varias fotos con Arducam IMX477 usando Picamera2 y las guarda en /mnt/usbdrive/
"""
import subprocess
import time
import datetime
import signal
import os
from picamera2 import Picamera2, Preview

def timestamp():
	return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

def main():
	num = 100
	espera = 10
	ruta = "/mnt/usbdrive/"

	if not os.path.isdir(ruta):
		print(f"¡Error, no existe la ruta {ruta}!")
		exit()

	picam2 = Picamera2()
	config = picam2.create_still_configuration(
		lores = {"size":(1280,720)},
		main = {"size":(1920,1080)},
		display = "lores"
		)
	picam2.configure(config)

	print("Iniciando preview DRM")
	picam2.start_preview(Preview.DRM)

	picam2.start()
	print("Camara iniciada")

	time.sleep(2)

	print(f"Iniciando bucle para tomar {num} fotos")

	try:
		for i in range(num):
			if i!=0:
				print("Esperando para tomar foto")
				time.sleep(espera)

			filename = f"{ruta}fotoA{timestamp()}.jpg"
			print("Tomando foto")

			picam2.capture_file(filename)
			print("Foto guardada")

	except Exception as e:
		print(f"Ocuarrio un error durante la captura {e}")

	except KeyboardInterrupt:
		print("Captura interrumpida por el usuario")

	finally:
		print("Deteniendo camara y preview")
		picam2.stop_preview()
		picam2.stop()
		print("Programa detenido")

if __name__ == "__main__":
	main()
