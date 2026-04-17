#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TuxGuard Database Module
Zentrale Datenbankoperationen für Benutzer und Gesichtserkennung
"""

import sqlite3
import logging
import hashlib
import hmac
import os
from pathlib import Path
from typing import List, Optional, Tuple
import numpy as np

from config import Config

logger = logging.getLogger('TuxGuard.Database')

class DatabaseError(Exception):
    """Benutzerdefinierte Exception für Datenbankfehler"""
    pass

class SecurityUtils:
    """Utilities für Sicherheitsfunktionen"""
    
    @staticmethod
    def hash_pin_pbkdf2(pin: str, iterations: int = Config.PBKDF2_ITERATIONS) -> str:
        """Erstellt einen sicheren PBKDF2-Hash einer PIN"""
        salt = os.urandom(32).hex()
        dk = hashlib.pbkdf2_hmac('sha256', pin.encode('utf-8'), 
                                bytes.fromhex(salt), iterations)
        return f"pbkdf2_sha256${iterations}${salt}${dk.hex()}"
    
    @staticmethod
    def verify_pin(pin: str, stored: str) -> bool:
        """Verifiziert eine PIN gegen den gespeicherten Hash"""
        if stored.startswith("pbkdf2_sha256$"):
            try:
                _, iters_str, salt_hex, hash_hex = stored.split("$", 3)
                iters = int(iters_str)
                dk = hashlib.pbkdf2_hmac('sha256', pin.encode('utf-8'), 
                                       bytes.fromhex(salt_hex), iters).hex()
                return hmac.compare_digest(dk, hash_hex)
            except Exception:
                return False
        # Legacy SHA256 Support
        return hmac.compare_digest(hashlib.sha256(pin.encode('utf-8')).hexdigest(), stored)
    
    @staticmethod
    def upgrade_pin_hash(cursor: sqlite3.Cursor, pin: str, stored: str) -> None:
        """Upgraded legacy PIN-Hashes auf PBKDF2"""
        if not stored.startswith("pbkdf2_sha256$"):
            new_hash = SecurityUtils.hash_pin_pbkdf2(pin)
            cursor.execute("UPDATE users SET pin_hash=? WHERE pin_hash=?", 
                          (new_hash, stored))

class DatabaseManager:
    """Zentrale Datenbankoperationen"""
    
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or Config.get_database_path()
        self.conn = None
        self.cursor = None
        
    def connect(self):
        """Stellt Verbindung zur Datenbank her"""
        try:
            self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            self.cursor = self.conn.cursor()
            self._create_tables()
            logger.info(f"Datenbankverbindung hergestellt: {self.db_path}")
        except Exception as e:
            logger.error(f"Datenbankverbindung fehlgeschlagen: {e}")
            raise DatabaseError(f"Kann nicht zur Datenbank verbinden: {e}")
    
    def disconnect(self):
        """Schließt die Datenbankverbindung"""
        if self.conn:
            self.conn.close()
            logger.info("Datenbankverbindung geschlossen")
    
    def _create_tables(self):
        """Erstellt die erforderlichen Datenbanktabellen"""
        try:
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    pin_hash TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS face_encodings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    face_encoding BLOB NOT NULL,
                    description TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
                )
            """)
            
            self.conn.commit()
            logger.debug("Datenbanktabellen erstellt/überprüft")
        except Exception as e:
            logger.error(f"Fehler beim Erstellen der Tabellen: {e}")
            raise DatabaseError(f"Tabellenerstellung fehlgeschlagen: {e}")
    
    def get_thread_connection(self) -> Tuple[sqlite3.Connection, sqlite3.Cursor]:
        """Erstellt eine neue Datenbankverbindung für Thread-Sicherheit"""
        conn = sqlite3.connect(str(self.db_path))
        return conn, conn.cursor()
    
    def add_user(self, name: str, pin: str) -> int:
        """Fügt einen neuen Benutzer hinzu"""
        if len(pin) < Config.MIN_PIN_LENGTH:
            raise ValueError(f"PIN muss mindestens {Config.MIN_PIN_LENGTH} Zeichen lang sein")
        
        pin_hash = SecurityUtils.hash_pin_pbkdf2(pin)
        
        try:
            self.cursor.execute("INSERT INTO users (name, pin_hash) VALUES (?, ?)", 
                              (name, pin_hash))
            user_id = self.cursor.lastrowid
            self.conn.commit()
            logger.info(f"Benutzer '{name}' hinzugefügt (ID: {user_id})")
            return user_id
        except sqlite3.IntegrityError:
            raise ValueError(f"Benutzername '{name}' existiert bereits")
        except Exception as e:
            logger.error(f"Fehler beim Hinzufügen des Benutzers: {e}")
            raise DatabaseError(f"Benutzer konnte nicht hinzugefügt werden: {e}")
    
    def add_face_encoding(self, user_id: int, face_encoding: np.ndarray, 
                         description: str = "") -> int:
        """Fügt eine Gesichtskodierung für einen Benutzer hinzu"""
        try:
            encoding_blob = sqlite3.Binary(face_encoding.tobytes())
            self.cursor.execute(
                "INSERT INTO face_encodings (user_id, face_encoding, description) VALUES (?, ?, ?)",
                (user_id, encoding_blob, description)
            )
            encoding_id = self.cursor.lastrowid
            self.conn.commit()
            logger.debug(f"Gesichtskodierung hinzugefügt (ID: {encoding_id}) für Benutzer {user_id}")
            return encoding_id
        except Exception as e:
            logger.error(f"Fehler beim Hinzufügen der Gesichtskodierung: {e}")
            raise DatabaseError(f"Gesichtskodierung konnte nicht hinzugefügt werden: {e}")
    
    def get_all_users(self) -> List[Tuple[int, str]]:
        """Gibt alle Benutzer zurück"""
        try:
            self.cursor.execute("SELECT id, name FROM users ORDER BY name")
            return self.cursor.fetchall()
        except Exception as e:
            logger.error(f"Fehler beim Abrufen der Benutzer: {e}")
            raise DatabaseError(f"Benutzer konnten nicht abgerufen werden: {e}")
    
    def get_user_face_encodings(self, user_name: str) -> List[Tuple[str, np.ndarray]]:
        """Gibt alle Gesichtskodierungen für einen Benutzer zurück"""
        try:
            self.cursor.execute("""
                SELECT fe.description, fe.face_encoding 
                FROM face_encodings fe 
                JOIN users u ON fe.user_id = u.id 
                WHERE u.name = ?
            """, (user_name,))
            
            results = []
            for desc, encoding_blob in self.cursor.fetchall():
                encoding = np.frombuffer(encoding_blob, dtype=np.float64)
                results.append((desc, encoding))
            
            return results
        except Exception as e:
            logger.error(f"Fehler beim Abrufen der Gesichtskodierungen: {e}")
            raise DatabaseError(f"Gesichtskodierungen konnten nicht abgerufen werden: {e}")
    
    def get_all_face_encodings(self) -> List[Tuple[str, np.ndarray, str]]:
        """Gibt alle Gesichtskodierungen mit Benutzernamen zurück"""
        try:
            self.cursor.execute("""
                SELECT u.name, fe.face_encoding, fe.description 
                FROM users u 
                JOIN face_encodings fe ON u.id = fe.user_id
            """)
            
            results = []
            for name, encoding_blob, desc in self.cursor.fetchall():
                encoding = np.frombuffer(encoding_blob, dtype=np.float64)
                results.append((name, encoding, desc))
            
            return results
        except Exception as e:
            logger.error(f"Fehler beim Abrufen aller Gesichtskodierungen: {e}")
            raise DatabaseError(f"Gesichtskodierungen konnten nicht abgerufen werden: {e}")
    
    def verify_user_pin(self, pin: str) -> bool:
        """Verifiziert eine PIN gegen alle Benutzer"""
        try:
            self.cursor.execute("SELECT pin_hash FROM users LIMIT 1")
            row = self.cursor.fetchone()
            if not row:
                return False
            
            stored_hash = row[0]
            is_valid = SecurityUtils.verify_pin(pin, stored_hash)
            
            # Upgrade legacy hash falls nötig
            if is_valid and not stored_hash.startswith("pbkdf2_sha256$"):
                SecurityUtils.upgrade_pin_hash(self.cursor, pin, stored_hash)
                self.conn.commit()
                logger.info("PIN-Hash auf PBKDF2 aktualisiert")
            
            return is_valid
        except Exception as e:
            logger.error(f"Fehler bei PIN-Verifikation: {e}")
            return False
    
    def delete_user(self, user_name: str) -> bool:
        """Löscht einen Benutzer und alle zugehörigen Daten"""
        try:
            # Lösche zuerst alle Gesichtskodierungen
            self.cursor.execute("""
                DELETE FROM face_encodings 
                WHERE user_id IN (SELECT id FROM users WHERE name = ?)
            """, (user_name,))
            
            # Lösche dann den Benutzer
            self.cursor.execute("DELETE FROM users WHERE name = ?", (user_name,))
            
            deleted_count = self.cursor.rowcount
            self.conn.commit()
            
            if deleted_count > 0:
                logger.info(f"Benutzer '{user_name}' gelöscht")
                return True
            else:
                logger.warning(f"Benutzer '{user_name}' nicht gefunden")
                return False
                
        except Exception as e:
            logger.error(f"Fehler beim Löschen des Benutzers: {e}")
            raise DatabaseError(f"Benutzer konnte nicht gelöscht werden: {e}")
    
    def __enter__(self):
        """Context Manager Eintritt"""
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context Manager Austritt"""
        self.disconnect()