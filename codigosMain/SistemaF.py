#!/usr/bin/env python3
import sys
import cv2
import numpy as np
import threading
import time
import socket
import pandas as pd 
from ultralytics import YOLO

from PyQt5 import QtWidgets, QtCore, QtGui
from PyQt5.QtGui import QStandardItemModel, QStandardItem
from PyQt5.QtMultimedia import QSound
from interfazF import Ui_MainWindow
from auth import verificar_usuario, cerrar_sesion, registrar_evento, actualizar_eventos_actuales, obtener_sesiones_con_eventos

# --- 1. CONFIGURACIÓN DEL PIPELINE GSTREAMER ---
def gstreamer_pipeline(port):
    # Se añade un timeout de 1 segundo (1000000000 ns) para no bloquear GStreamer si se corta la red
    return (
        f"udpsrc port={port} timeout=1000000000 ! "
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
        self.grabbed = False
        self.frame = None
        self.stopped = False
        self.lock = threading.Lock()
        
        # Frame negro de respaldo puro para evitar fallos en YOLO
        self.black_frame = np.zeros((360, 640, 3), dtype=np.uint8)
        self.cap = None

        self.t = threading.Thread(target=self.update, args=())
        self.t.daemon = True
        self.t.start()

    def _conectar_camara(self):
        """Inicializa o reinicia el pipeline de GStreamer de forma segura."""
        if self.cap is not None:
            self.cap.release()
        self.cap = cv2.VideoCapture(gstreamer_pipeline(self.port), cv2.CAP_GSTREAMER)

    def update(self):
        self._conectar_camara()
        
        while not self.stopped:
            if self.cap is None or not self.cap.isOpened():
                time.sleep(2)
                self._conectar_camara()
                continue
                
            grabbed, frame = self.cap.read()
            
            if grabbed and frame is not None:
                with self.lock:
                    self.grabbed = True
                    self.frame = frame
            else:
                with self.lock:
                    self.grabbed = False
                    self.frame = None
                
                if self.cap is not None:
                    self.cap.release()
                
                # 5 segundos para que la GPU de NVIDIA limpie el contexto y no se congele
                time.sleep(5)
                self._conectar_camara()

    def read(self):
        with self.lock:
            if self.frame is None:
                return False, self.black_frame.copy()
            return self.grabbed, self.frame.copy()

    def stop(self):
        self.stopped = True
        self.t.join()
        if self.cap is not None:
            self.cap.release()

# --- FUNCIONES DE CONTROL UDP ---
def send_control_command(server_ip: str, server_port: int, message: str) -> None:
    """Envía un comando UDP al controlador físico mediante un hilo asíncrono para no bloquear la inferencia por tiempos de espera DNS."""
    def tarea_envio():
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.sendto(message.encode(), (server_ip, server_port))
            s.close()
        except Exception:
            pass
            
    t = threading.Thread(target=tarea_envio)
    t.daemon = True
    t.start()

# --- 3. WORKER THREAD (YOLO EN SEGUNDO PLANO) ---
class YoloWorker(QtCore.QThread):
    image_update = QtCore.pyqtSignal(list)
    eventos_update = QtCore.pyqtSignal()

    def __init__(self):
        super().__init__()
        self.running = True
        self.camaras = []
        self.modelo = None
        self.sesion_id = None 
        
        # IPS locales de los dispositivos (mDNS o fijas)
        self.rpi_ips = ["cam1.local", "cam2.local", "cam3.local"]
        self.rpi_ports = [6000, 6000, 6000]
        
        # NUEVO: Control de tiempo para evitar registros constantes y spam de audio
        self.ultimo_registro = [0.0, 0.0, 0.0]
        self.tiempo_cooldown = 10.0  # Segundos que deben pasar para registrar un nuevo evento en la misma cámara
        
    def set_sesion(self, sesion_id):
        self.sesion_id = sesion_id

    def run(self):
        print("--- INICIANDO SISTEMA EN SEGUNDO PLANO ---")
        print("Cargando modelo YOLO Batch=3...")
        try:
            self.modelo = YOLO("modelov3y11.engine", task="detect")
        except Exception as e:
            print(f"Error cargando modelo: {e}. Revise la ruta del archivo .engine")
            return

        print("Modelo cargado. Iniciando cámaras...")
        self.camaras = [CameraStream(5001), CameraStream(5002), CameraStream(5003)]
        
        estado_deteccion = [False, False, False] 
        
        print("Esperando estabilización de sensores (2s)...")
        time.sleep(2)
        print("--- SISTEMA LISTO PARA INFERENCIA ---")

        while self.running:
            start_time = time.time()
            
            # 1. Leer frames y registrar qué cámaras están activas realmente
            frames_raw = []
            camaras_activas = [] 
            
            for cam in self.camaras:
                grabbed, f = cam.read()
                frames_raw.append(f)
                camaras_activas.append(grabbed)

            # Si no hay ninguna cámara enviando video, evitamos consumir CPU en cuadros negros
            if not any(camaras_activas):
                time.sleep(0.1)
                continue

            # 2. Inferencia Batch
            resultados = self.modelo(frames_raw, conf=0.3, verbose=False, imgsz=640, half=True)

            # 3. Anotar frames
            frames_anotados = []
            for i, r in enumerate(resultados):
                frames_anotados.append(r.plot())
                
                # Ignorar cálculos y envíos de red si la cámara específica está fuera de línea
                if not camaras_activas[i]:
                    estado_deteccion[i] = False
                    continue 
                
                hay_deteccion = len(r.boxes) > 0 and r.boxes.conf.max().item() > 0.2
                
                if hay_deteccion:
                    boxes = r.boxes.xyxy.cpu().numpy()
                    box = boxes[0] 
                    obj_cx = (box[0] + box[2]) / 2
                    obj_cy = (box[1] + box[3]) / 2
                    
                    send_control_command(self.rpi_ips[i], self.rpi_ports[i], f"TARGET {obj_cx:.1f} {obj_cy:.1f}")
                    
                    if not estado_deteccion[i]:
                        # NUEVO: Solo registra el evento y suena el audio si superó el tiempo de cooldown
                        tiempo_actual = time.time()
                        if tiempo_actual - self.ultimo_registro[i] > self.tiempo_cooldown:
                            if self.sesion_id is not None:
                                registrar_evento(self.sesion_id, i+1, r.boxes.conf.max().item(), "0", "hola")
                                self.eventos_update.emit() # Esta señal es la que activa reproducir_sonido() en el hilo principal
                            self.ultimo_registro[i] = tiempo_actual
                            
                        estado_deteccion[i] = True 
                else:
                    send_control_command(self.rpi_ips[i], self.rpi_ports[i], "LOST")
                    estado_deteccion[i] = False

            # 4. Emitir señal a la interfaz
            self.image_update.emit(frames_anotados)
            
            # 5. Limitador a ~30 FPS para no ahogar la cola de eventos de PyQt
            tiempo_procesamiento = time.time() - start_time
            tiempo_espera = max(0.0, 0.033 - tiempo_procesamiento)
            time.sleep(tiempo_espera)
            
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
        
        for display in [self.displayCam1, self.displayCam2, self.displayCam3]:
            display.setStyleSheet("background-color: black; border: 1px solid gray;")
            display.setScaledContents(True)

        self.sesion_id = None
        self.tabWidget.setTabEnabled(1, False)
        self.botonInicioSesion.clicked.connect(self.handle_login)
        self.tabWidget.currentChanged.connect(self.prevent_tab_change)
        self.regreso.clicked.connect(self.ir_a_principal)
        
        self.reporteAntiguo.clicked.connect(self.abrir_pestana_descargas)
        self.selectorSesion.currentIndexChanged.connect(self.mostrar_tabla_pasada)
        self.descargar.clicked.connect(self.descargar_reporte_seleccionado)
        
        self.modelo_eventos_pasados = QStandardItemModel()
        self.modelo_eventos_pasados.setHorizontalHeaderLabels(["Cámara", "Confianza", "Hora"])
        self.vistaDeEventos.setModel(self.modelo_eventos_pasados)
        
        header_pasado = self.vistaDeEventos.horizontalHeader()
        header_pasado.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        header_pasado.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        header_pasado.setSectionResizeMode(2, QtWidgets.QHeaderView.Stretch)
        
        self.descargarEventosSesion.clicked.connect(self.descargar_reporte_actual)

        self.nombres_camaras = ["Cámara 1", "Cámara 2", "Cámara 3", "Desactivado"]
        self.combo_boxes = [self.selectorCam1, self.selectorCam2, self.selectorCam3]
        for idx, combo in enumerate(self.combo_boxes):
            combo.addItems(self.nombres_camaras)
            combo.setCurrentIndex(idx if idx < 3 else 3)

        self.modelo_eventos = QStandardItemModel()
        self.modelo_eventos.setHorizontalHeaderLabels(["Cámara", "Confianza", "Hora"])
        self.displayEventos.setModel(self.modelo_eventos)
        
        header = self.displayEventos.horizontalHeader()
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QtWidgets.QHeaderView.Stretch)

        self.yolo_worker = YoloWorker()
        self.yolo_worker.image_update.connect(self.actualizar_displays)
        self.yolo_worker.eventos_update.connect(self.refrescar_tabla_eventos)
        self.yolo_worker.eventos_update.connect(self.reproducir_sonido)
        self.yolo_worker.start()
        
        app = QtWidgets.QApplication.instance()
        app.aboutToQuit.connect(self.cleanup)
    
    def refrescar_tabla_eventos(self):
        if self.sesion_id is None:
            return
            
        filas = actualizar_eventos_actuales(self.sesion_id)
        self.modelo_eventos.setRowCount(0)
        
        if filas:
            for fila in filas:
                item_camara = QStandardItem(f"Cámara {fila[0]}")
                item_confianza = QStandardItem(f"{fila[1]:.2f}")
                
                try:
                    hora = pd.to_datetime(fila[2])
                    if hora.tzinfo is None:
                        hora = hora.tz_localize('UTC')
                    hora_mex = hora.tz_convert('America/Mexico_City').strftime('%Y-%m-%d %H:%M:%S')
                except Exception:
                    hora_mex = str(fila[2])
                
                item_hora = QStandardItem(hora_mex)
                
                item_camara.setTextAlignment(QtCore.Qt.AlignCenter)
                item_confianza.setTextAlignment(QtCore.Qt.AlignCenter)
                item_hora.setTextAlignment(QtCore.Qt.AlignCenter)
                
                self.modelo_eventos.appendRow([item_camara, item_confianza, item_hora])
                
        self.displayEventos.scrollToBottom()        

    def handle_login(self):
        usuario = self.usuario.text()
        contrasena = self.contrasena.text()
        sesion_id = verificar_usuario(usuario, contrasena)
        
        if sesion_id:
            self.sesion_id = sesion_id
            self.yolo_worker.set_sesion(sesion_id) 
            QtWidgets.QMessageBox.information(self, "Login exitoso", f"Sesión iniciada.\nID: {sesion_id}")
            self.tabWidget.setTabEnabled(1, True)
            self.tabWidget.setCurrentIndex(1)
        else:
            QtWidgets.QMessageBox.warning(self, "Login fallido", "Usuario o contraseña incorrectos.")

    def actualizar_displays(self, frames_anotados):
        if self.tabWidget.currentIndex() == 0:
            return

        displays = [self.displayCam1, self.displayCam2, self.displayCam3]
        
        for i, display in enumerate(displays):
            seleccion = self.combo_boxes[i].currentText()
            imagen_final = None
            
            if seleccion == "Cámara 1" and len(frames_anotados) > 0:
                imagen_final = frames_anotados[0]
            elif seleccion == "Cámara 2" and len(frames_anotados) > 1:
                imagen_final = frames_anotados[1]
            elif seleccion == "Cámara 3" and len(frames_anotados) > 2:
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
        self.tabWidget.setCurrentIndex(2)

    def ir_a_principal(self):
        self.tabWidget.setCurrentIndex(1)

    def cleanup(self):
        print("Cerrando aplicación...")
        if self.yolo_worker.isRunning():
            self.yolo_worker.stop()
        if self.sesion_id:
            cerrar_sesion(self.sesion_id)
            
    def descargar_reporte_actual(self):
        if self.sesion_id is None:
            QtWidgets.QMessageBox.warning(self, "Error", "No hay una sesión activa para descargar.")
            return
            
        filas = actualizar_eventos_actuales(self.sesion_id)
        
        if not filas:
            QtWidgets.QMessageBox.information(self, "Sin datos", "No hay eventos registrados en esta sesión aún.")
            return

        opciones = QtWidgets.QFileDialog.Options()
        nombre_por_defecto = f"Reporte_Sesion_{self.sesion_id}.xlsx"
        
        ruta_archivo, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, 
            "Guardar Reporte de Eventos", 
            nombre_por_defecto, 
            "Archivos Excel (*.xlsx);;Todos los archivos (*)", 
            options=opciones
        )

        if ruta_archivo:
            try:
                df = pd.DataFrame(filas, columns=["Cámara", "Nivel de Confianza", "Fecha y Hora"])
                df["Cámara"] = "Cámara " + df["Cámara"].astype(str)
                df["Nivel de Confianza"] = df["Nivel de Confianza"].apply(lambda x: f"{x:.2f}")

                df.to_excel(ruta_archivo, index=False, engine='openpyxl')
                QtWidgets.QMessageBox.information(self, "Éxito", f"Reporte guardado correctamente en:\n{ruta_archivo}")
                
            except Exception as e:
                QtWidgets.QMessageBox.critical(self, "Error", f"No se pudo guardar el archivo.\nDetalle: {str(e)}\n\n¿Tienes instaladas las librerías pandas y openpyxl?")

    def abrir_pestana_descargas(self):
        self.ir_a_descargas() 
        self.selectorSesion.blockSignals(True) 
        self.selectorSesion.clear()
        
        sesiones = obtener_sesiones_con_eventos()
        
        if not sesiones:
            self.selectorSesion.addItem("No hay historial disponible", userData=None)
        else:
            for sesion_id, fecha in sesiones:
                texto_visual = f"Sesión {sesion_id}  |  Fecha: {fecha}"
                self.selectorSesion.addItem(texto_visual, userData=sesion_id)
                
        self.selectorSesion.blockSignals(False)
        self.mostrar_tabla_pasada()

    def mostrar_tabla_pasada(self):
        self.modelo_eventos_pasados.setRowCount(0)
        sesion_id = self.selectorSesion.currentData()
        
        if not sesion_id:
            return
            
        filas = actualizar_eventos_actuales(sesion_id)
        
        if filas:
            for fila in filas:
                item_camara = QStandardItem(f"Cámara {fila[0]}")
                item_confianza = QStandardItem(f"{fila[1]:.2f}")
                
                # Convertir UTC a hora de México
                try:
                    hora = pd.to_datetime(fila[2])
                    if hora.tzinfo is None:
                        hora = hora.tz_localize('UTC')
                    hora_mex = hora.tz_convert('America/Mexico_City').strftime('%Y-%m-%d %H:%M:%S')
                except Exception:
                    hora_mex = str(fila[2])
                
                item_hora = QStandardItem(hora_mex)
                
                item_camara.setTextAlignment(QtCore.Qt.AlignCenter)
                item_confianza.setTextAlignment(QtCore.Qt.AlignCenter)
                item_hora.setTextAlignment(QtCore.Qt.AlignCenter)
                
                self.modelo_eventos_pasados.appendRow([item_camara, item_confianza, item_hora])

    def descargar_reporte_seleccionado(self):
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
                try:
                    df["Fecha y Hora"] = pd.to_datetime(df["Fecha y Hora"])
                    if df["Fecha y Hora"].dt.tz is None:
                        df["Fecha y Hora"] = df["Fecha y Hora"].dt.tz_localize('UTC')
                    df["Fecha y Hora"] = df["Fecha y Hora"].dt.tz_convert('America/Mexico_City').dt.strftime('%Y-%m-%d %H:%M:%S')
                except Exception as e:
                    pass # En caso de que la tabla esté vacía o el formato sea incorrecto, lo ignora

                df.to_excel(ruta_archivo, index=False, engine='openpyxl')
                QtWidgets.QMessageBox.information(self, "Éxito", f"Historial guardado correctamente en:\n{ruta_archivo}")
            except Exception as e:
                QtWidgets.QMessageBox.critical(self, "Error", f"No se pudo guardar el archivo.\nDetalle: {str(e)}") 
    
    def reproducir_sonido(self):
        QSound.play("dronedetected.wav")

def main():
    app = QtWidgets.QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
