#!/usr/bin/env python3
# abrirTransmicionInterfaz_overlay.py
# Receptor UDP/H264 integrado en Qt usando GstVideoOverlay correctamente:
# - selecciona un sink con overlay disponible según la plataforma
# - espera a que el widget tenga window handle (showEvent) antes de set_window_handle
# - PAUSED -> set_window_handle -> PLAYING
# Si no se puede incrustar hace fallback e informa en consola.

import sys
import gi
import platform
from PyQt5 import QtWidgets, QtCore

gi.require_version("Gst", "1.0")
gi.require_version("GstVideo", "1.0")
from gi.repository import Gst, GstVideo

Gst.init(None)

from interfaz import Ui_MainWindow

# Lista de sinks por plataforma (probamos en orden hasta encontrar uno disponible)
_SINK_CANDIDATES = {
    "Windows": ["d3dvideosink", "dxgisink", "directdrawsink", "glimagesink", "autovideosink"],
    "Linux": ["glimagesink", "xvimagesink", "ximagesink", "autovideosink"],
    "Darwin": ["glimagesink", "autovideosink"]  # macOS
}

def find_available_sink():
    plt = platform.system()
    candidates = _SINK_CANDIDATES.get(plt, ["autovideosink"])
    found = []
    for name in candidates:
        try:
            factory = Gst.ElementFactory.find(name)
            available = factory is not None
        except Exception:
            available = False
        print(f"[SinkCheck] {name}: {'OK' if available else 'NO'}")
        if available:
            return name
    # último recurso
    print("[SinkCheck] Ningún sink preferido encontrado; usando autovideosink como fallback.")
    return "autovideosink"

class GstOverlayReceiver(QtCore.QObject):
    def __init__(self, widget, port=5000, parent=None):
        super().__init__(parent)
        self.widget = widget
        self.port = port
        self.pipeline = None
        self.sink_element = None
        self.sink_name = find_available_sink()
        self._started = False

    def build_pipeline(self):
        # Construimos pipeline con sink elegido y lo nombramos 'videosink' para poder localizarlo.
        # Usamos decodebin para mayor compatibilidad.
        pipeline_str = (
            f'udpsrc port={self.port} caps="application/x-rtp, media=video, clock-rate=90000, encoding-name=H264, payload=96" '
            f'! rtph264depay ! h264parse ! decodebin ! videoconvert ! {self.sink_name} name=videosink sync=false'
        )
        try:
            self.pipeline = Gst.parse_launch(pipeline_str)
        except Exception as e:
            print("[GstOverlayReceiver] Error creando pipeline:", e)
            self.pipeline = None
            return False

        self.sink_element = self.pipeline.get_by_name("videosink")
        if not self.sink_element:
            print("[GstOverlayReceiver] No se pudo localizar el elemento 'videosink' en el pipeline.")
            return False
        return True

    def start(self):
        if self._started:
            return True
        if not self.build_pipeline():
            return False

        # Arrancar en PAUSED para poder establecer el window handle con seguridad
        self.pipeline.set_state(Gst.State.PAUSED)

        # Intentar obtener el elemento real que implementa VideoOverlay.
        overlay_elem = None
        # Si el element mismo implementa la interfaz, úsalo; en algunos casos autovideosink es un bin
        try:
            if isinstance(self.sink_element, GstVideo.VideoOverlay):
                overlay_elem = self.sink_element
        except Exception:
            overlay_elem = None

        # Si sink_element es un bin, buscar dentro hijos un elemento que implemente overlay
        if overlay_elem is None:
            try:
                # get_children puede no existir para todos los tipos; iteramos por pads y elementos del bin
                # Intentaremos iterar por todos los elementos del pipeline y encontrar el que implemente VideoOverlay
                it = self.pipeline.iterate_elements()
                res = it.next()
                while True:
                    try:
                        elem = res.get()
                        try:
                            if isinstance(elem, GstVideo.VideoOverlay):
                                overlay_elem = elem
                                break
                        except Exception:
                            pass
                        res = it.next()
                    except StopIteration:
                        break
            except Exception:
                # alternativa: intentar tomar sink_element en cualquier caso
                pass

        # Si aún no encontramos overlay_elem, intentamos usar sink_element directamente y esperamos que funcione
        target_overlay = overlay_elem if overlay_elem is not None else self.sink_element

        # Asegurarnos que el widget tiene handle nativo; esto debe llamarse después de show()
        try:
            win_id = int(self.widget.winId())
        except Exception as e:
            print("[GstOverlayReceiver] No pude obtener winId del widget:", e)
            win_id = None

        if win_id is None or win_id == 0:
            print("[GstOverlayReceiver] El widget no tiene window handle válido aún. Asegúrate de llamar start después de show().")
            # Intentamos seguir de todos modos; el usuario puede reintentar start() después del show.
            self.pipeline.set_state(Gst.State.PLAYING)
            self._started = True
            return True

        # Establecer window handle en el overlay element
        try:
            GstVideo.VideoOverlay.set_window_handle(target_overlay, win_id)
            print("[GstOverlayReceiver] set_window_handle OK en el elemento de sink.")
        except Exception as e:
            print("[GstOverlayReceiver] Error al setear window handle en el sink:", e)
            # Continuar; algunos sinks ignoran set_window_handle y abren su propia ventana.

        # Finalmente poner en PLAYING
        self.pipeline.set_state(Gst.State.PLAYING)
        self._started = True
        print(f"[GstOverlayReceiver] Pipeline iniciado en puerto {self.port} con sink '{self.sink_name}'.")
        return True

    def stop(self):
        if self.pipeline:
            self.pipeline.set_state(Gst.State.NULL)
            self.pipeline = None
            self._started = False
            print("[GstOverlayReceiver] Pipeline detenido")

class MainWindow(QtWidgets.QMainWindow, Ui_MainWindow):
    def __init__(self, gst_port=5000):
        super().__init__()
        self.setupUi(self)

        # Asegurarnos de que displayCam1 tenga ventana nativa para overlay
        self.displayCam1.setAttribute(QtCore.Qt.WA_NativeWindow, True)
        # Fondo negro para evitar parpadeos si el sink no pinta inmediatamente
        self.displayCam1.setStyleSheet("background-color: black;")
        self.displayCam1.setText("")

        self._gst_port = gst_port
        self.receiver = GstOverlayReceiver(widget=self.displayCam1, port=gst_port)

        # Conectar cierre para asegurar limpieza
        app = QtWidgets.QApplication.instance()
        app.aboutToQuit.connect(self.cleanup)

    def showEvent(self, event):
        super().showEvent(event)
        # El widget ya se mostró; ahora el winId() debe ser válido. Iniciamos el receiver.
        started = self.receiver.start()
        if not started:
            print("[MainWindow] No se pudo iniciar overlay receiver; revisa la salida anterior para errores.")

    def cleanup(self):
        self.receiver.stop()

def main():
    app = QtWidgets.QApplication(sys.argv)
    window = MainWindow(gst_port=5000)
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()