import time
import os
import datetime
from picamera2 import Picamera2, Preview

def timestamp():
	return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

def main():
	ruta = "/mnt/usbdrive/"

	if not os.path.isdir(ruta):
		exit()

	picam2 = Picamera2()

	config = picam2.create_still_configuration(
			main = {"size": (1920,1080)},
			lores = {"size": (1280, 720)},
			display = "lores"
		)

	picam2.configure(config)

	picam2.start_preview(Preview.DRM)

	picam2.start()

	time.sleep(2)

	print("Captura manual iniciada")
	print("Preciona ENTER para tomar foto")
	print("Escribe 'q' y preciona ENTER para salir")

	try:
		while True:
			user_input = input()

			if user_input.lower() == 'q':

				print("Saliendo")
				break

			filename = f"{ruta}fotoM_{timestamp()}.jpg"
			picam2.capture_file(filename)

			print(f"Foto guardada. Presiona ENTER para otra foto, o 'q' para salir.")

	except Exception as e:
		print(f"Ocurrio un error durante la captura: {e}")

	except KeyboardInterrupt:
		print("\nCaptura interrumpida por el usuario (Ctrl+C)")

	finally:
		print("Deteniendo captura")
		picam2.stop_preview()
		picam2.stop()
		print("Programa terminado")

if __name__ == "__main__":
	main()
