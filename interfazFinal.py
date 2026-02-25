#!/usr/bin/env python3
import sys
import cv2
import numpy as np
import threading
import time
from ultralytics import YOLO

from PyQt5 import QtWidgets, QtCore, QtGui
from interfaz import Ui_MainWindow
from auth import verificar_usuario, cerrar_sesion, registrar_evento, actualizar_eventos_actuales

# --- 1. CONFIGURACIÓN DEL PIPELINE GSTREAMER ---
def gstreamer_pipeline(port):
    return (
        f"udpsrc port={port} ! "
        "application/x-rtp, encoding-name=H264, payload=96 ! "
        "rtph264depay ! h264parse ! "
        "nvv4l2decoder ! nvvidconv ! "
        "video/x-raw, width=640, height=360 ! "
        "videoconvert ! video/x-raw, format=BGR ! "
        "appsink sync=false drop=true max-buffers=1"
    )

# --- 2. CLASE DE LECTURA DE CÁMARA (HILOS) ---
class CameraStream:
    def __init__(self, port):
        self.port = port
        self.cap = cv2.VideoCapture(gstreamer_pipeline(port), cv2.CAP_GSTREAMER)
        self.grabbed, self.frame = self.cap.read()
        self.stopped = False
        self.lock = threading.Lock()
        
        # Frame negro de respaldo
        self.black_frame = np.zeros((360, 640, 3), dtype=np.uint8)

        if not self.cap.isOpened():
            print(f"Advertencia: Cámara en puerto {port} no abrió.")

        self.t = threading.Thread(target=self.update, args=())
        self.t.daemon = True
        self.t.start()

    def update(self):
        while not self.stopped:
            if not self.cap.isOpened():
                time.sleep(0.1)
                continue
            grabbed, frame = self.cap.read()
            if grabbed:
                with self.lock:
                    self.grabbed = grabbed
                    self.frame = frame
            else:
                pass 

    def read(self):
        with self.lock:
            if self.frame is None:
                return False, self.black_frame
            return self.grabbed, self.frame

    def stop(self):
        self.stopped = True
        self.t.join()
        self.cap.release()

# --- 3. WORKER THREAD (YOLO EN SEGUNDO PLANO) ---
class YoloWorker(QtCore.QThread):
    image_update = QtCore.pyqtSignal(list)

    def __init__(self):
        super().__init__()
        self.running = True
        self.camaras = []
        self.modelo = None
        # NUEVO: Agregamos una variable para almacenar la sesión actual
        self.sesion_id = None 
        
    def set_sesion(self, sesion_id):
        # NUEVO: Método para que MainWindow actualice la sesión aquí
        self.sesion_id = sesion_id

    def run(self):
        print("--- INICIANDO SISTEMA EN SEGUNDO PLANO ---")
        print("Cargando modelo YOLO Batch=3...")
        try:
            self.modelo = YOLO("dron.engine", task="detect")
        except Exception as e:
            print(f"Error cargando modelo: {e}. Revise la ruta del archivo .engine")
            return

        print("Modelo cargado. Iniciando cámaras...")
        self.camaras = [CameraStream(5000), CameraStream(5001), CameraStream(5002)]
        regAnt = 0
        
        print("Esperando estabilización de sensores (2s)...")
        time.sleep(2)
        print("--- SISTEMA LISTO PARA INFERENCIA ---")

        while self.running:
            # 1. Leer frames
            frames_raw = []
            for cam in self.camaras:
                _, f = cam.read()
                frames_raw.append(f)

            # 2. Inferencia Batch
            resultados = self.modelo(frames_raw, verbose=False, imgsz=640, half=True)

            # 3. Anotar frames
            frames_anotados = []
            for i, r in enumerate(resultados):
                frames_anotados.append(r.plot())
                
                # Modificado para usar self.sesion_id y comprobar que no sea None
                if len(r.boxes) > 0 and r.boxes.conf.max().item() > 0.2 and regAnt != i+1:
                    if self.sesion_id is not None: # Solo registra si alguien hizo login
                        # Corrección: era r.boxes.conf.max().item() (faltaban los paréntesis en max)
                        registrar_evento(self.sesion_id, i+1, r.boxes.conf.max().item(), "0", "hola")
                        
                        actualizar_eventos_actuales(self.sesion_id)
                    regAnt = i+1

            # 4. Emitir señal a la interfaz
            self.image_update.emit(frames_anotados)
            

        # Limpieza
        for cam in self.camaras:
            cam.stop()

    def stop(self):
        self.running = False
        self.wait()

# --- 4. VENTANA PRINCIPAL ---
class MainWindow(QtWidgets.QMainWindow, Ui_MainWindow):
    def __init__(self):
        super().__init__()
        self.setupUi(self)
        self.tabWidget.tabBar().hide()
        
        self.tabWidget.setCurrentIndex(0)
        
        self.contrasena.setEchoMode(QtWidgets.QLineEdit.Password)
        
        # Configurar displays
        for display in [self.displayCam1, self.displayCam2, self.displayCam3]:
            display.setStyleSheet("background-color: black; border: 1px solid gray;")
            display.setScaledContents(True)

        # -- Login
        self.sesion_id = None
        self.tabWidget.setTabEnabled(1, False)
        self.botonInicioSesion.clicked.connect(self.handle_login)
        self.tabWidget.currentChanged.connect(self.prevent_tab_change)
        
        self.reporteAntiguo.clicked.connect(self.ir_a_descargas)
        self.regreso.clicked.connect(self.ir_a_principal)

        # -- Configuración de ComboBoxes --
        self.nombres_camaras = ["Cámara 1", "Cámara 2", "Cámara 3", "Desactivado"]
        self.combo_boxes = [self.selectorCam1, self.selectorCam2, self.selectorCam3]
        for idx, combo in enumerate(self.combo_boxes):
            combo.addItems(self.nombres_camaras)
            combo.setCurrentIndex(idx if idx < 3 else 3)

        # -- INICIO AUTOMÁTICO DEL WORKER --
        # Aquí está el cambio: Iniciamos el hilo inmediatamente al abrir la App
        self.yolo_worker = YoloWorker()
        self.yolo_worker.image_update.connect(self.actualizar_displays)
        self.yolo_worker.start()  # <--- SE EJECUTA AHORA, NO AL LOGUEARSE
        
        app = QtWidgets.QApplication.instance()
        app.aboutToQuit.connect(self.cleanup)

    def handle_login(self):
        usuario = self.usuario.text()
        contrasena = self.contrasena.text()
        sesion_id = verificar_usuario(usuario, contrasena)
        
        if sesion_id:
            self.sesion_id = sesion_id
            
            # NUEVO: Le pasamos el ID al Worker que ya está corriendo
            self.yolo_worker.set_sesion(sesion_id) 
            
            QtWidgets.QMessageBox.information(self, "Login exitoso", f"Sesión iniciada.\nID: {sesion_id}")
            self.tabWidget.setTabEnabled(1, True)
            self.tabWidget.setCurrentIndex(1)
        else:
            QtWidgets.QMessageBox.warning(self, "Login fallido", "Usuario o contraseña incorrectos.")

    def actualizar_displays(self, frames_anotados):
        # Optimización opcional: Si el usuario está en la pantalla de login (index 0),
        # no gastamos CPU convirtiendo imágenes, aunque el worker siga procesando.
        if self.tabWidget.currentIndex() == 0:
            return

        displays = [self.displayCam1, self.displayCam2, self.displayCam3]
        
        for i, display in enumerate(displays):
            seleccion = self.combo_boxes[i].currentText()
            
            imagen_final = None
            if seleccion == "Cámara 1":
                imagen_final = frames_anotados[0]
            elif seleccion == "Cámara 2":
                imagen_final = frames_anotados[1]
            elif seleccion == "Cámara 3":
                imagen_final = frames_anotados[2]
            
            if imagen_final is not None:
                imagen_rgb = cv2.cvtColor(imagen_final, cv2.COLOR_BGR2RGB)
                h, w, ch = imagen_rgb.shape
                bytes_per_line = ch * w
                qt_image = QtGui.QImage(imagen_rgb.data, w, h, bytes_per_line, QtGui.QImage.Format_RGB888)
                display.setPixmap(QtGui.QPixmap.fromImage(qt_image))
            else:
                display.clear()

    def prevent_tab_change(self, index):
        if self.sesion_id is None and index == 1:
            self.tabWidget.setCurrentIndex(0)

    def ir_a_descargas(self):
        # Cambia a la pestaña de descargarReporte (índice 2)
        self.tabWidget.setCurrentIndex(2)

    def ir_a_principal(self):
        # Regresa a la pestaña de interfazPrincipal (índice 1)
        self.tabWidget.setCurrentIndex(1)

    def cleanup(self):
        print("Cerrando aplicación...")
        if self.yolo_worker.isRunning():
            self.yolo_worker.stop()
        if self.sesion_id:
            cerrar_sesion(self.sesion_id)

def main():
    app = QtWidgets.QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
