# -*- coding: utf-8 -*-
"""
Created on Sun Nov  9 17:02:18 2025

@author: dtrej
"""

import sqlite3
import os
from datetime import datetime

# Obtén la ruta a la base de datos (ajusta la ruta si tu .db está en otro lado)
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