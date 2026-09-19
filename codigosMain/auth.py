# -*- coding: utf-8 -*-
"""
Created on Sun Nov  9 17:02:18 2025

@author: dtrej
"""

import sqlite3
import os
from datetime import datetime

DB_PATH = "database.db"

def get_db_connection(db_path=DB_PATH):
    return sqlite3.connect(db_path)

def verificar_usuario(usuario, contrasena):
    """
    Verifica que el usuario y la contraseña sean correctos.
    Si es correcto, registra el inicio de sesión y retorna el id de sesión.
    Si no, retorna None.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # Verificar usuario y contraseña
        cur.execute("SELECT id FROM Usuarios WHERE usuario=? AND contrasena=?", (usuario, contrasena))
        row = cur.fetchone()
        if not row:
            return None  # Credenciales incorrectas
        usuario_id = row[0]

        # Registrar inicio de sesión
        cur.execute("INSERT INTO Sesiones (usuario_id) VALUES (?)", (usuario_id,))
        conn.commit()
        sesion_id = cur.lastrowid
        return sesion_id  # Login y registro correcto

    finally:
        conn.close()

def cerrar_sesion(sesion_id):
    """Actualiza la hora de cierre de sesión para la sesión indicada."""
    if not sesion_id:
        return
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    try:
        cur.execute(
            "UPDATE Sesiones SET fin_sesion=CURRENT_TIMESTAMP WHERE id=?",
            (sesion_id,)
        )
        conn.commit()
    finally:
        conn.close()

def obtener_usuario_id(usuario):
    """Devuelve el id de usuario dado su nombre."""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT id FROM Usuarios WHERE usuario=?", (usuario,))
        row = cur.fetchone()
        return row[0] if row else None
    finally:
        conn.close()

def registrar_evento(sesion_id, id_camara, confianza, bounding_box, ruta_captura):
    """
    Registra un evento de detección de dron en la base de datos.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # Especificamos las columnas (omitiendo 'id' para que se autogenere)
        # Usamos CURRENT_TIMESTAMP o datetime('now', 'localtime') según cómo prefieras la hora
        query = """
            INSERT INTO EventosDeteccion 
            (sesion_id, timestamp, id_camara, confianza, bounding_box, ruta_captura) 
            VALUES (?, CURRENT_TIMESTAMP, ?, ?, ?, ?)
        """
        
        # Ejecutamos la consulta pasando las variables de forma segura (tupla)
        cur.execute(query, (sesion_id, id_camara, confianza, bounding_box, ruta_captura))
        conn.commit()
        
        # Opcional: Imprimir en consola o devolver el ID generado
        evento_id = cur.lastrowid
        #print(f"Evento registrado en BD con éxito (ID: {evento_id})")
        return evento_id

    except sqlite3.Error as e:
        #print(f"Error en base de datos al registrar evento: {e}")
        return None
        
    finally:
        conn.close()
        
def actualizar_eventos_actuales(sesion_id):
    """
    Obtiene e imprime en la terminal todos los eventos de detección de la sesión actual.
    """
    # Si la sesión es None, no hacemos la consulta
    if not sesion_id:
        print("No hay una sesión activa para consultar eventos.")
        return None

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # Usamos id_camara (como en tu INSERT) e incluimos el timestamp.
        # Recuerda la coma en (sesion_id,)
        cur.execute("SELECT id_camara, confianza, timestamp FROM EventosDeteccion WHERE sesion_id=?", (sesion_id,))
        
        # fetchall() obtiene todos los registros que coincidan
        filas = cur.fetchall() 
        
        if filas:
            print(f"\n--- EVENTOS DE LA SESIÓN {sesion_id} ---")
            for fila in filas:
                camara = fila[0]
                confianza = fila[1]
                tiempo = fila[2]
                print(f"[{tiempo}] Cámara {camara} - Dron detectado (Confianza: {confianza:.2f})")
            print("----------------------------------\n")
        else:
            print(f"No hay eventos registrados aún para la sesión {sesion_id}.")
            
        return filas

    except sqlite3.Error as e:
        print(f"Error al leer la base de datos: {e}")
        return None
        
    finally:
        conn.close()

def obtener_sesiones_con_eventos():
    """
    Obtiene una lista de las sesiones que tienen eventos registrados, 
    junto con la fecha exacta de su primera detección.
    """
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # Hacemos un JOIN para obtener solo las sesiones que tienen eventos
        # y extraemos el timestamp del evento más antiguo de esa sesión para usarlo como fecha.
        cur.execute("""
            SELECT s.id, MIN(e.timestamp) 
            FROM Sesiones s
            JOIN EventosDeteccion e ON s.id = e.sesion_id
            GROUP BY s.id
            ORDER BY s.id DESC
        """)
        return cur.fetchall() # Devuelve una lista de tuplas: [(id_sesion, fecha), ...]
    except sqlite3.Error as e:
        print(f"Error al obtener historial de sesiones: {e}")
        return []
    finally:
        conn.close()
