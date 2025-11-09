#!/usr/bin/env python3
import sys
from PyQt5 import QtWidgets, QtCore
from interfaz import Ui_MainWindow
from recibirCamara import GstOverlayReceiver
from auth import verificar_usuario, cerrar_sesion  # <--- asegúrate de importar cerrar_sesion

class MainWindow(QtWidgets.QMainWindow, Ui_MainWindow):
    def __init__(self, gst_port=5000):
        super().__init__()
        self.setupUi(self)
        self.tabWidget.tabBar().hide()
        self.contrasena.setEchoMode(QtWidgets.QLineEdit.Password)
        # -- GStreamer Receiver (lo que ya tienes)
        self.displayCam1.setAttribute(QtCore.Qt.WA_NativeWindow, True)
        self.displayCam1.setStyleSheet("background-color: black;")
        self.displayCam1.setText("")
        self._gst_port = gst_port
        self.receiver = GstOverlayReceiver(widget=self.displayCam1, port=gst_port)
        app = QtWidgets.QApplication.instance()
        app.aboutToQuit.connect(self.cleanup)

        # -- Login
        self.sesion_id = None
        self.tabWidget.setTabEnabled(1, False)  # DESHABILITA la pestaña principal al inicio
        self.botonInicioSesion.clicked.connect(self.handle_login)

        # Opcional: Previene cambio de pestaña por teclado o mouse [Extra seguridad]
        self.tabWidget.currentChanged.connect(self.prevent_tab_change)

    def showEvent(self, event):
        super().showEvent(event)
        started = self.receiver.start()
        if not started:
            print("[MainWindow] No se pudo iniciar overlay receiver; revisa la salida anterior para errores.")

    def handle_login(self):
        usuario = self.usuario.text()
        contrasena = self.contrasena.text()
        sesion_id = verificar_usuario(usuario, contrasena)
        if sesion_id:
            self.sesion_id = sesion_id
            QtWidgets.QMessageBox.information(self, "Login exitoso", f"Sesión iniciada.\nID sesión: {sesion_id}")
            self.tabWidget.setTabEnabled(1, True)      # Activa la pestaña principal
            self.tabWidget.setCurrentIndex(1)          # Cambia a la pestaña principal
        else:
            QtWidgets.QMessageBox.warning(self, "Login fallido", "Usuario o contraseña incorrectos.")

    def prevent_tab_change(self, index):
        # Si aún no hay sesión y quiere ir a la principal, lo devuelve al login
        if self.sesion_id is None and index == 1:
            self.tabWidget.setCurrentIndex(0)

    def cleanup(self):
        self.receiver.stop()
        if self.sesion_id:
            cerrar_sesion(self.sesion_id)

def main():
    app = QtWidgets.QApplication(sys.argv)
    window = MainWindow(gst_port=5000)
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()