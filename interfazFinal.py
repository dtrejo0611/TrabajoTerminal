#!/usr/bin/env python3
import sys
import cv2
import numpy as np
import threading
import time
import pandas as pd 
from ultralytics import YOLO

from PyQt5 import QtWidgets, QtCore, QtGui
from PyQt5.QtGui import QStandardItemModel, QStandardItem
from PyQt5.QtMultimedia import QSound
from interfazF import Ui_MainWindow
from auth import verificar_usuario, cerrar_sesion, registrar_evento, actualizar_eventos_actuales, obtener_sesiones_con_eventos

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
    eventos_update = QtCore.pyqtSignal()

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
        
        # --- CAMBIO AQUÍ ---
        # En lugar de regAnt = 0, usamos una lista para rastrear las 3 cámaras individualmente
        estado_deteccion = [False, False, False] 
        
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
                
                # --- CAMBIO AQUÍ ---
                # Verificamos si en este frame exacto hay una detección válida
                hay_deteccion = len(r.boxes) > 0 and r.boxes.conf.max().item() > 0.2
                
                if hay_deteccion:
                    # Si hay detección, pero la cámara NO estaba detectando nada antes (es un evento nuevo)
                    if not estado_deteccion[i]:
                        if self.sesion_id is not None:
                            registrar_evento(self.sesion_id, i+1, r.boxes.conf.max().item(), "0", "hola")
                            self.eventos_update.emit()
                        # Marcamos esta cámara como "detectando activamente" para que no vuelva a registrar
                        estado_deteccion[i] = True 
                else:
                    # Si el dron desaparece de la cámara, reiniciamos el estado a False
                    # Esto permite que se vuelva a registrar un evento si el dron vuelve a aparecer
                    estado_deteccion[i] = False

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
        self.regreso.clicked.connect(self.ir_a_principal)
        
        self.reporteAntiguo.clicked.connect(self.abrir_pestana_descargas) # Carga los datos al cambiar de pestaña
        self.selectorSesion.currentIndexChanged.connect(self.mostrar_tabla_pasada) # Actualiza tabla al cambiar selección
        self.descargar.clicked.connect(self.descargar_reporte_seleccionado) # Botón de descargar
        
        self.modelo_eventos_pasados = QStandardItemModel()
        self.modelo_eventos_pasados.setHorizontalHeaderLabels(["Cámara", "Confianza", "Hora"])
        self.vistaDeEventos.setModel(self.modelo_eventos_pasados)
        
        header_pasado = self.vistaDeEventos.horizontalHeader()
        header_pasado.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        header_pasado.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        header_pasado.setSectionResizeMode(2, QtWidgets.QHeaderView.Stretch)
        
        self.descargarEventosSesion.clicked.connect(self.descargar_reporte_actual)

        # -- Configuración de ComboBoxes --
        self.nombres_camaras = ["Cámara 1", "Cámara 2", "Cámara 3", "Desactivado"]
        self.combo_boxes = [self.selectorCam1, self.selectorCam2, self.selectorCam3]
        for idx, combo in enumerate(self.combo_boxes):
            combo.addItems(self.nombres_camaras)
            combo.setCurrentIndex(idx if idx < 3 else 3)

        # --- CONFIGURACIÓN DE LA TABLA DE EVENTOS ---
        self.modelo_eventos = QStandardItemModel()
        self.modelo_eventos.setHorizontalHeaderLabels(["Cámara", "Confianza", "Hora"])
        self.displayEventos.setModel(self.modelo_eventos)
        
        # Ajustar el ancho de las columnas para que se vea bien
        header = self.displayEventos.horizontalHeader()
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QtWidgets.QHeaderView.Stretch) # La hora ocupa el resto del espacio

        # --- CONEXIÓN DE LA SEÑAL DEL WORKER ---
        self.yolo_worker = YoloWorker()
        self.yolo_worker.image_update.connect(self.actualizar_displays)
        self.yolo_worker.eventos_update.connect(self.refrescar_tabla_eventos) # <--- CONECTAMOS LA SEÑAL
        self.yolo_worker.eventos_update.connect(self.reproducir_sonido)
        self.yolo_worker.start()
        
        
        app = QtWidgets.QApplication.instance()
        app.aboutToQuit.connect(self.cleanup)
    
    def refrescar_tabla_eventos(self):
        if self.sesion_id is None:
            return
            
        # Obtenemos las filas de la BD gracias a tu función de auth.py
        filas = actualizar_eventos_actuales(self.sesion_id)
        
        # Limpiamos los datos actuales de la tabla (por si hay datos viejos)
        self.modelo_eventos.setRowCount(0)
        
        if filas:
            for fila in filas:
                # Tu función retorna: id_camara (0), confianza (1), timestamp (2)
                item_camara = QStandardItem(f"Cámara {fila[0]}")
                item_confianza = QStandardItem(f"{fila[1]:.2f}")
                item_hora = QStandardItem(str(fila[2]))
                
                # Centramos el texto para que se vea estético
                item_camara.setTextAlignment(QtCore.Qt.AlignCenter)
                item_confianza.setTextAlignment(QtCore.Qt.AlignCenter)
                item_hora.setTextAlignment(QtCore.Qt.AlignCenter)
                
                # Añadimos la fila completa a la tabla
                self.modelo_eventos.appendRow([item_camara, item_confianza, item_hora])
                
        # Hacemos scroll automático hacia el evento más reciente (abajo)
        self.displayEventos.scrollToBottom()        

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
            
    def descargar_reporte_actual(self):
        # 1. Validar que haya una sesión iniciada
        if self.sesion_id is None:
            QtWidgets.QMessageBox.warning(self, "Error", "No hay una sesión activa para descargar.")
            return
            
        # 2. Obtener los datos usando tu función existente en auth.py
        filas = actualizar_eventos_actuales(self.sesion_id)
        
        if not filas:
            QtWidgets.QMessageBox.information(self, "Sin datos", "No hay eventos registrados en esta sesión aún.")
            return

        # 3. Abrir ventana de diálogo para elegir dónde guardar el archivo
        opciones = QtWidgets.QFileDialog.Options()
        nombre_por_defecto = f"Reporte_Sesion_{self.sesion_id}.xlsx"
        
        ruta_archivo, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, 
            "Guardar Reporte de Eventos", 
            nombre_por_defecto, 
            "Archivos Excel (*.xlsx);;Todos los archivos (*)", 
            options=opciones
        )

        # 4. Si el usuario seleccionó una ruta (no canceló)
        if ruta_archivo:
            try:
                # Convertimos las filas (tuplas) a un DataFrame de pandas
                # Tu base de datos devuelve: id_camara, confianza, timestamp
                df = pd.DataFrame(filas, columns=["Cámara", "Nivel de Confianza", "Fecha y Hora"])
                
                # Damos un poco de formato (opcional): agregar prefijo a la cámara y redondear confianza
                df["Cámara"] = "Cámara " + df["Cámara"].astype(str)
                df["Nivel de Confianza"] = df["Nivel de Confianza"].apply(lambda x: f"{x:.2f}")

                # Guardamos como Excel
                df.to_excel(ruta_archivo, index=False, engine='openpyxl')
                
                QtWidgets.QMessageBox.information(self, "Éxito", f"Reporte guardado correctamente en:\n{ruta_archivo}")
                
            except Exception as e:
                QtWidgets.QMessageBox.critical(self, "Error", f"No se pudo guardar el archivo.\nDetalle: {str(e)}\n\n¿Tienes instaladas las librerías pandas y openpyxl?")

    def abrir_pestana_descargas(self):
        """Prepara el ComboBox y abre la pestaña de descargas pasadas."""
        self.ir_a_descargas() # Cambia a la pestaña
        
        # Bloqueamos las señales temporalmente para que no intente actualizar la tabla mientras se llena la lista
        self.selectorSesion.blockSignals(True) 
        self.selectorSesion.clear()
        
        # Obtenemos el historial de la BD
        sesiones = obtener_sesiones_con_eventos()
        
        if not sesiones:
            self.selectorSesion.addItem("No hay historial disponible", userData=None)
        else:
            for sesion_id, fecha in sesiones:
                texto_visual = f"Sesión {sesion_id}  |  Fecha: {fecha}"
                # Guardamos el texto visible, y escondemos el 'sesion_id' en la propiedad userData
                self.selectorSesion.addItem(texto_visual, userData=sesion_id)
                
        self.selectorSesion.blockSignals(False) # Reactivamos las señales
        
        # Forzamos a mostrar los datos de la primera opción de la lista
        self.mostrar_tabla_pasada()

    def mostrar_tabla_pasada(self):
        """Llena la tabla 'vistaDeEventos' con los datos de la sesión seleccionada."""
        self.modelo_eventos_pasados.setRowCount(0) # Limpiar datos viejos de la tabla
        
        # Extraemos el ID real de la sesión que guardamos en userData
        sesion_id = self.selectorSesion.currentData()
        
        if not sesion_id:
            return
            
        # Reciclamos tu función de auth.py para obtener las filas
        filas = actualizar_eventos_actuales(sesion_id)
        
        if filas:
            for fila in filas:
                item_camara = QStandardItem(f"Cámara {fila[0]}")
                item_confianza = QStandardItem(f"{fila[1]:.2f}")
                item_hora = QStandardItem(str(fila[2]))
                
                item_camara.setTextAlignment(QtCore.Qt.AlignCenter)
                item_confianza.setTextAlignment(QtCore.Qt.AlignCenter)
                item_hora.setTextAlignment(QtCore.Qt.AlignCenter)
                
                self.modelo_eventos_pasados.appendRow([item_camara, item_confianza, item_hora])

    def descargar_reporte_seleccionado(self):
        """Genera el archivo Excel de la sesión seleccionada en el ComboBox."""
        sesion_id = self.selectorSesion.currentData()
        
        if not sesion_id:
            QtWidgets.QMessageBox.warning(self, "Aviso", "No hay ninguna sesión válida seleccionada.")
            return
            
        filas = actualizar_eventos_actuales(sesion_id)
        
        if not filas:
            QtWidgets.QMessageBox.information(self, "Sin datos", "Esta sesión no contiene eventos para descargar.")
            return

        opciones = QtWidgets.QFileDialog.Options()
        nombre_por_defecto = f"Historial_Sesion_{sesion_id}.xlsx"
        
        ruta_archivo, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, 
            "Guardar Reporte Pasado", 
            nombre_por_defecto, 
            "Archivos Excel (*.xlsx);;Todos los archivos (*)", 
            options=opciones
        )

        if ruta_archivo:
            try:
                # Usamos pandas igual que en el reporte actual
                df = pd.DataFrame(filas, columns=["Cámara", "Nivel de Confianza", "Fecha y Hora"])
                df["Cámara"] = "Cámara " + df["Cámara"].astype(str)
                df["Nivel de Confianza"] = df["Nivel de Confianza"].apply(lambda x: f"{x:.2f}")

                df.to_excel(ruta_archivo, index=False, engine='openpyxl')
                QtWidgets.QMessageBox.information(self, "Éxito", f"Historial guardado correctamente en:\n{ruta_archivo}")
            except Exception as e:
                QtWidgets.QMessageBox.critical(self, "Error", f"No se pudo guardar el archivo.\nDetalle: {str(e)}") 
    
    def reproducir_sonido(self):
        """Reproduce un archivo de audio .wav personalizado."""
        # Asegúrate de que el archivo alerta.wav exista en tu carpeta
        QSound.play("dronedetected.wav")

def main():
    app = QtWidgets.QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
