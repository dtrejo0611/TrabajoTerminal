import gi
import sys
import threading
import time

# --- INICIO DE LA SOLUCIÓN ---
# 1. Importar ctypes para llamar a la función C de X11
import ctypes
try:
    # 2. Cargar la librería X11
    x11 = ctypes.CDLL('libX11.so')
    # 3. Llamar a XInitThreads() para hacerla "thread-safe"
    x11.XInitThreads()
except:
    print("Advertencia: No se pudo llamar a XInitThreads().")
# --- FIN DE LA SOLUCIÓN ---


gi.require_version('Gst', '1.0')
from gi.repository import Gst, GObject, GLib

# --- BUENA PRÁCTICA ---
# Inicializar explícitamente el sistema de hilos de GObject/GLib
GObject.threads_init()
# ---------------------

import numpy as np
import cv2

Gst.init(None)

# ... (El resto de tu código permanece exactamente igual) ...

class GStreamerPipeline:
    def __init__(self, pipeline_desc):
        self.pipeline = Gst.parse_launch(pipeline_desc)
        self.loop = GLib.MainLoop()
        self.bus = self.pipeline.get_bus()
        self.bus.add_signal_watch()
        self.bus.connect("message", self.on_message)
        self.thread = threading.Thread(target=self.run_pipeline)
        
        # --- Cambios para OpenCV ---
        self.last_frame = None  # Aquí guardamos el último frame recibido
        self.frame_lock = threading.Lock() # Un candado para proteger self.last_frame
        self.stop_stream = False
        # -------------------------

        # Appsink setup
        self.appsink = self.pipeline.get_by_name("mysink")
        self.appsink.set_property("emit-signals", True)
        self.appsink.connect("new-sample", self.on_new_sample)

    def on_message(self, bus, message):
        t = message.type
        if t == Gst.MessageType.EOS or t == Gst.MessageType.ERROR:
            err, debug = (message.parse_error() if t == Gst.MessageType.ERROR else (None, None))
            print(f"\n[GStreamer] Stream detenido. ERROR: {err if err else 'EOS'}")
            self.stop()
        return True

    def on_new_sample(self, sink):
        sample = sink.emit("pull-sample")
        if not sample:
            return Gst.FlowReturn.ERROR

        buf = sample.get_buffer()
        caps = sample.get_caps()
        
        s = caps.get_structure(0)
        width = s.get_value("width")
        height = s.get_value("height")

        success, map_info = buf.map(Gst.MapFlags.READ)
        if not success:
            return Gst.FlowReturn.ERROR
        
        try:
            # --- ¡CAMBIO! ---
            # El formato I420 tiene una altura de 1.5 * alto_real
            frame = np.ndarray(
                (int(height * 1.5), width), # Shape (alto * 1.5, ancho)
                dtype=np.uint8,
                buffer=map_info.data
            )
            # --- FIN DEL CAMBIO ---
            
            with self.frame_lock:
                self.last_frame = frame.copy() 
                
        finally:
            buf.unmap(map_info)
            
        return Gst.FlowReturn.OK

    # --- Nueva función para obtener el frame de forma segura ---
    def get_frame(self):
        """Obtiene el último frame de forma segura."""
        frame_to_return = None
        with self.frame_lock:
            if self.last_frame is not None:
                frame_to_return = self.last_frame.copy()
        return frame_to_return
    # ---------------------------------------------------------

    def run_pipeline(self):
        self.pipeline.set_state(Gst.State.PLAYING)
        self.loop.run()

    def start(self):
        print("▶️ Iniciando reproducción en hilo separado...")
        self.thread.start()

    def stop(self):
        self.stop_stream = True # Señal para que el hilo principal se detenga
        if self.loop.is_running():
            self.loop.quit()
        if self.pipeline:
            self.pipeline.set_state(Gst.State.NULL)
        


# --- Ejecución Principal (HILO PRINCIPAL / HILO DE GUI) ---
if __name__ == "__main__":
    
    # --- PIPELINE CORREGIDO (NVMM -> NV12 -> BGR) ---
    PIPELINE_DESCRIPTION = (
        "udpsrc port=5000 caps=\"application/x-rtp, media=video, clock-rate=90000, encoding-name=H264, payload=96\" "
        "! rtpjitterbuffer "
        "! rtph264depay ! h264parse ! nvv4l2decoder "  # 2. Decodifica a NVMM (hardware)
        # --- INICIO DEL CAMBIO ---
        # 3. Convierte de NVMM (hardware) a NV12 (RAM)
        "! nvvidconv "
        "! video/x-raw, format=NV12 "
        # 4. Convierte de NV12 (RAM) a BGR (RAM) usando la CPU
        "! videoconvert "
        "! video/x-raw, format=BGR "
        # --- FIN DEL CAMBIO ---
        "! appsink sync=false max-buffers=1 drop=true name=mysink"
    )

    client = GStreamerPipeline(PIPELINE_DESCRIPTION)
    client.start()
    # ... (el resto del código de inicio sigue igual) ...
    
    # ... (El resto de tu código de bucle principal es correcto y no necesita cambios) ...

    print("✅ Cliente iniciado. Presiona 's' para guardar un frame o 'q' para salir.")
    
    try:
        while client.thread.is_alive() and not client.stop_stream:
            
            frame_i420 = client.get_frame() # <-- Este frame está en formato I420
            
            if frame_i420 is not None:
                
                # --- ¡CAMBIO! ---
                # Convertimos el frame de I420 a BGR usando OpenCV
                frame_bgr = cv2.cvtColor(frame_i420, cv2.COLOR_YUV2BGR_I420)
                # --- FIN DEL CAMBIO ---

                # Ahora mostramos el frame BGR
                cv2.imshow("Stream (Jetson)", frame_bgr) 
                key = cv2.waitKey(1) & 0xFF

                if key == ord('s'):
                    fname = f"frame_{int(time.time())}.png"
                    cv2.imwrite(fname, frame_bgr) # Guardamos el BGR
                    print(f"Frame guardado como {fname}")
                
                if key == ord('q'):
                    print("Cerrando...")
                    client.stop() 
                    break
            else:
                time.sleep(0.01)
    
    except KeyboardInterrupt:
        print("\n[Ctrl+C detectado] Enviando señal de detención al GStreamer...")
    
    finally:
        # Asegurarse de que todo se detenga y limpie
        client.stop()
        if client.thread.is_alive():
            client.thread.join()
        cv2.destroyAllWindows() # Cerrar ventanas de OpenCV

    print("Programa finalizado y recursos liberados.")