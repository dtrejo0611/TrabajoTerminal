# -*- coding: utf-8 -*-
"""
Created on Sun Nov  9 16:57:54 2025

@author: dtrej
"""

import platform
import gi

gi.require_version("Gst", "1.0")
gi.require_version("GstVideo", "1.0")
from gi.repository import Gst, GstVideo
from PyQt5 import QtCore

Gst.init(None)

# Sinks sugeridos por plataforma
_SINK_CANDIDATES = {
    "Windows": ["d3dvideosink", "dxgisink", "directdrawsink", "glimagesink", "autovideosink"],
    "Linux": ["glimagesink", "xvimagesink", "ximagesink", "autovideosink"],
    "Darwin": ["glimagesink", "autovideosink"]  # macOS
}

def find_available_sink():
    plt = platform.system()
    candidates = _SINK_CANDIDATES.get(plt, ["autovideosink"])
    for name in candidates:
        try:
            factory = Gst.ElementFactory.find(name)
            available = factory is not None
        except Exception:
            available = False
        print(f"[SinkCheck] {name}: {'OK' if available else 'NO'}")
        if available:
            return name
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

        self.pipeline.set_state(Gst.State.PAUSED)
        overlay_elem = None

        try:
            if isinstance(self.sink_element, GstVideo.VideoOverlay):
                overlay_elem = self.sink_element
        except Exception:
            overlay_elem = None

        if overlay_elem is None:
            try:
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
                pass

        target_overlay = overlay_elem if overlay_elem is not None else self.sink_element

        try:
            win_id = int(self.widget.winId())
        except Exception as e:
            print("[GstOverlayReceiver] No pude obtener winId del widget:", e)
            win_id = None

        if win_id is None or win_id == 0:
            print("[GstOverlayReceiver] El widget no tiene window handle válido aún. Asegúrate de llamar start después de show().")
            self.pipeline.set_state(Gst.State.PLAYING)
            self._started = True
            return True

        try:
            GstVideo.VideoOverlay.set_window_handle(target_overlay, win_id)
            print("[GstOverlayReceiver] set_window_handle OK en el elemento de sink.")
        except Exception as e:
            print("[GstOverlayReceiver] Error al setear window handle en el sink:", e)

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