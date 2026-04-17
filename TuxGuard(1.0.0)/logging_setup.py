#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TuxGuard Logging Module
Zentrales Logging-System für die Anwendung
"""

import logging
import logging.handlers
import os
from pathlib import Path
from config import Config

def setup_logging():
    """Richtet das zentrale Logging-System ein"""
    # Stelle sicher, dass Logs-Verzeichnis existiert
    Config.ensure_directories()
    
    # Erstelle Logger
    logger = logging.getLogger('TuxGuard')
    logger.setLevel(logging.DEBUG)
    
    # Verhindere doppelte Handler
    if logger.handlers:
        return logger
    
    # Formatierung
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(threadName)s - %(message)s'
    )
    
    # Handler für Hauptlog-Datei
    main_handler = logging.handlers.RotatingFileHandler(
        str(Config.LOG_FILE),
        maxBytes=Config.LOG_MAX_BYTES,
        backupCount=Config.LOG_BACKUP_COUNT,
        encoding='utf-8'
    )
    main_handler.setLevel(logging.DEBUG)
    main_handler.setFormatter(formatter)
    
    # Handler für Fehler-Log
    error_handler = logging.handlers.RotatingFileHandler(
        str(Config.ERROR_LOG_FILE),
        maxBytes=Config.LOG_MAX_BYTES,
        backupCount=Config.LOG_BACKUP_COUNT,
        encoding='utf-8'
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)
    
    # Handler für Konsole
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s'
    ))
    
    # Handler hinzufügen
    logger.addHandler(main_handler)
    logger.addHandler(error_handler)
    logger.addHandler(console_handler)
    
    return logger

def get_logger(name: str = 'TuxGuard'):
    """Gibt einen Logger zurück"""
    return logging.getLogger(name)