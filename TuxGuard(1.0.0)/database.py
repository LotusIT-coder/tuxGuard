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
                    password_hash TEXT,
                    is_admin INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS face_encodings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    face_encoding BLOB NOT NULL,
                    description TEXT,
                    image_data BLOB,
                    source_filename TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
                )
            """)

            self._ensure_face_encoding_columns()
            self._ensure_user_columns()
            self.conn.commit()
            logger.debug("Datenbanktabellen erstellt/überprüft")
        except Exception as e:
            logger.error(f"Fehler beim Erstellen der Tabellen: {e}")
            raise DatabaseError(f"Tabellenerstellung fehlgeschlagen: {e}")

    def _ensure_face_encoding_columns(self):
        """Ergänzt neue Spalten für Bildvorschau und Metadaten bei bestehenden Datenbanken."""
        self.cursor.execute("PRAGMA table_info(face_encodings)")
        columns = {row[1] for row in self.cursor.fetchall()}
        if "image_data" not in columns:
            self.cursor.execute("ALTER TABLE face_encodings ADD COLUMN image_data BLOB")
        if "source_filename" not in columns:
            self.cursor.execute("ALTER TABLE face_encodings ADD COLUMN source_filename TEXT")
        if "created_at" not in columns:
            self.cursor.execute("ALTER TABLE face_encodings ADD COLUMN created_at TIMESTAMP")

    def _ensure_user_columns(self):
        """Migriert ältere users-Tabellen auf das aktuelle Schema (Passwort, Admin-Flag)."""
        self.cursor.execute("PRAGMA table_info(users)")
        columns = {row[1] for row in self.cursor.fetchall()}
        if "password_hash" not in columns:
            self.cursor.execute("ALTER TABLE users ADD COLUMN password_hash TEXT")
        if "is_admin" not in columns:
            self.cursor.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0")

    def get_thread_connection(self) -> Tuple[sqlite3.Connection, sqlite3.Cursor]:
        """Erstellt eine neue Datenbankverbindung für Thread-Sicherheit"""
        conn = sqlite3.connect(str(self.db_path))
        return conn, conn.cursor()
    
    def add_user(self, name: str, pin: str, password: Optional[str] = None,
                 is_admin: bool = False) -> int:
        """Fügt einen neuen Benutzer hinzu.

        ``password`` ist optional; wird es übergeben, wird zusätzlich zur PIN ein
        Passwort-Hash gespeichert. ``is_admin`` markiert den Benutzer als Admin.
        """
        if len(pin) < Config.MIN_PIN_LENGTH:
            raise ValueError(f"PIN muss mindestens {Config.MIN_PIN_LENGTH} Zeichen lang sein")
        if password is not None and len(password) < Config.MIN_PASSWORD_LENGTH:
            raise ValueError(
                f"Passwort muss mindestens {Config.MIN_PASSWORD_LENGTH} Zeichen lang sein"
            )

        pin_hash = SecurityUtils.hash_pin_pbkdf2(pin)
        password_hash = SecurityUtils.hash_pin_pbkdf2(password) if password else None

        try:
            self.cursor.execute(
                "INSERT INTO users (name, pin_hash, password_hash, is_admin) VALUES (?, ?, ?, ?)",
                (name, pin_hash, password_hash, 1 if is_admin else 0),
            )
            user_id = self.cursor.lastrowid
            self.conn.commit()
            logger.info(
                "Benutzer '%s' hinzugefügt (ID: %s, admin=%s)", name, user_id, is_admin
            )
            return user_id
        except sqlite3.IntegrityError:
            raise ValueError(f"Benutzername '{name}' existiert bereits")
        except Exception as e:
            logger.error(f"Fehler beim Hinzufügen des Benutzers: {e}")
            raise DatabaseError(f"Benutzer konnte nicht hinzugefügt werden: {e}")
    
    def add_face_encoding(
        self,
        user_id: int,
        face_encoding: np.ndarray,
        description: str = "",
        image_data: Optional[bytes] = None,
        source_filename: Optional[str] = None,
    ) -> int:
        """Fügt eine Gesichtskodierung für einen Benutzer hinzu"""
        try:
            encoding_blob = sqlite3.Binary(face_encoding.tobytes())
            self.cursor.execute(
                """
                INSERT INTO face_encodings
                (user_id, face_encoding, description, image_data, source_filename)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    encoding_blob,
                    description,
                    sqlite3.Binary(image_data) if image_data is not None else None,
                    source_filename,
                )
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

    def get_user_id(self, user_name: str) -> Optional[int]:
        """Gibt die Benutzer-ID zu einem Namen zurück."""
        try:
            self.cursor.execute("SELECT id FROM users WHERE name = ?", (user_name,))
            row = self.cursor.fetchone()
            return row[0] if row else None
        except Exception as e:
            logger.error(f"Fehler beim Abrufen der Benutzer-ID: {e}")
            raise DatabaseError(f"Benutzer-ID konnte nicht abgerufen werden: {e}")
    
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

    def get_user_face_records(self, user_name: str) -> List[Tuple[int, str, Optional[bytes], Optional[str], str]]:
        """Gibt die gespeicherten Bilder und Metadaten für einen Benutzer zurück."""
        try:
            self.cursor.execute("PRAGMA table_info(face_encodings)")
            columns = {row[1] for row in self.cursor.fetchall()}
            has_created_at = "created_at" in columns
            created_at_select = "fe.created_at" if has_created_at else "NULL AS created_at"
            order_by = "ORDER BY fe.created_at ASC, fe.id ASC" if has_created_at else "ORDER BY fe.id ASC"

            self.cursor.execute(f"""
                SELECT fe.id, fe.description, fe.image_data, fe.source_filename, {created_at_select}
                FROM face_encodings fe
                JOIN users u ON fe.user_id = u.id
                WHERE u.name = ?
                {order_by}
            """, (user_name,))
            return self.cursor.fetchall()
        except Exception as e:
            logger.error(f"Fehler beim Abrufen der Bilddaten: {e}")
            raise DatabaseError(f"Bilddaten konnten nicht abgerufen werden: {e}")
    
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

    def verify_user_pin_for_user(self, user_name: str, pin: str) -> bool:
        """Verifiziert die PIN eines konkreten Benutzers."""
        if not user_name or not pin:
            return False
        try:
            self.cursor.execute("SELECT pin_hash FROM users WHERE name = ?", (user_name,))
            row = self.cursor.fetchone()
            if not row or not row[0]:
                return False

            stored_hash = row[0]
            is_valid = SecurityUtils.verify_pin(pin, stored_hash)

            # Upgrade legacy hash falls nötig
            if is_valid and not stored_hash.startswith("pbkdf2_sha256$"):
                SecurityUtils.upgrade_pin_hash(self.cursor, pin, stored_hash)
                self.conn.commit()
                logger.info("PIN-Hash auf PBKDF2 aktualisiert (Benutzer: %s)", user_name)

            return is_valid
        except Exception as e:
            logger.error(f"Fehler bei benutzerbezogener PIN-Verifikation: {e}")
            return False

    # ------------------------------------------------------------------
    # Passwort- / Admin-Verwaltung
    # ------------------------------------------------------------------

    def has_users(self) -> bool:
        """True, wenn mindestens ein Benutzer existiert."""
        try:
            self.cursor.execute("SELECT 1 FROM users LIMIT 1")
            return self.cursor.fetchone() is not None
        except Exception as e:
            logger.error(f"Fehler beim Prüfen auf vorhandene Benutzer: {e}")
            return False

    def has_admin(self) -> bool:
        """True, wenn mindestens ein Admin existiert."""
        try:
            self.cursor.execute("SELECT 1 FROM users WHERE is_admin = 1 LIMIT 1")
            return self.cursor.fetchone() is not None
        except Exception as e:
            logger.error(f"Fehler beim Prüfen auf vorhandene Admins: {e}")
            return False

    def get_users_with_meta(self) -> List[Tuple[int, str, bool, bool]]:
        """Liste aller Benutzer mit (id, name, is_admin, has_password)."""
        try:
            self.cursor.execute(
                "SELECT id, name, is_admin, password_hash FROM users ORDER BY name"
            )
            return [
                (row[0], row[1], bool(row[2]), bool(row[3]))
                for row in self.cursor.fetchall()
            ]
        except Exception as e:
            logger.error(f"Fehler beim Abrufen der Benutzer-Metadaten: {e}")
            return []

    def set_user_password(self, user_name: str, password: str) -> bool:
        """Setzt/aktualisiert das Passwort eines Benutzers."""
        if len(password) < Config.MIN_PASSWORD_LENGTH:
            raise ValueError(
                f"Passwort muss mindestens {Config.MIN_PASSWORD_LENGTH} Zeichen lang sein"
            )
        try:
            password_hash = SecurityUtils.hash_pin_pbkdf2(password)
            self.cursor.execute(
                "UPDATE users SET password_hash = ? WHERE name = ?",
                (password_hash, user_name),
            )
            self.conn.commit()
            return self.cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Fehler beim Setzen des Passworts: {e}")
            raise DatabaseError(f"Passwort konnte nicht gesetzt werden: {e}")

    def set_user_admin(self, user_name: str, is_admin: bool) -> bool:
        """Setzt/entfernt das Admin-Flag."""
        try:
            self.cursor.execute(
                "UPDATE users SET is_admin = ? WHERE name = ?",
                (1 if is_admin else 0, user_name),
            )
            self.conn.commit()
            return self.cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Fehler beim Setzen des Admin-Flags: {e}")
            return False

    def verify_user_password(self, user_name: str, password: str) -> bool:
        """Prüft das Passwort eines konkreten Benutzers."""
        if not password:
            return False
        try:
            self.cursor.execute(
                "SELECT password_hash FROM users WHERE name = ?", (user_name,)
            )
            row = self.cursor.fetchone()
            if not row or not row[0]:
                return False
            return SecurityUtils.verify_pin(password, row[0])
        except Exception as e:
            logger.error(f"Fehler bei Passwort-Verifikation: {e}")
            return False

    def find_user_by_password(self, password: str, admin_only: bool = False) -> Optional[Tuple[int, str, bool]]:
        """Sucht einen Benutzer, dessen Passwort matcht.

        Liefert (id, name, is_admin) oder ``None``. Bei ``admin_only=True``
        werden nur Admin-Benutzer berücksichtigt.
        """
        if not password:
            return None
        try:
            sql = "SELECT id, name, is_admin, password_hash FROM users WHERE password_hash IS NOT NULL"
            if admin_only:
                sql += " AND is_admin = 1"
            self.cursor.execute(sql)
            for uid, name, is_admin, stored in self.cursor.fetchall():
                if SecurityUtils.verify_pin(password, stored):
                    return (uid, name, bool(is_admin))
            return None
        except Exception as e:
            logger.error(f"Fehler bei Benutzer-Passwort-Suche: {e}")
            return None
    
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
    
    def delete_face_encoding(self, face_encoding_id: int) -> bool:
        """Löscht ein einzelnes Gesichtsbild/Encoding anhand seiner ID"""
        try:
            self.cursor.execute("DELETE FROM face_encodings WHERE id = ?", (face_encoding_id,))
            deleted_count = self.cursor.rowcount
            self.conn.commit()
            
            if deleted_count > 0:
                logger.info(f"Gesichtsbild {face_encoding_id} gelöscht")
                return True
            else:
                logger.warning(f"Gesichtsbild {face_encoding_id} nicht gefunden")
                return False
                
        except Exception as e:
            logger.error(f"Fehler beim Löschen des Gesichtsbildes: {e}")
            raise DatabaseError(f"Gesichtsbild konnte nicht gelöscht werden: {e}")
    
    def __enter__(self):
        """Context Manager Eintritt"""
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context Manager Austritt"""
        self.disconnect()
