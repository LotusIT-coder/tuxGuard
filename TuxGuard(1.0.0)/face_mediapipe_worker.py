#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Isolierter Worker für MediaPipe-Bildverarbeitung."""

import json
import sys

from face_mediapipe import (
    face_emotions,
    face_encodings,
    face_geometry,
    load_image_file,
)


def main() -> int:
    try:
        args = sys.argv[1:]
        if not args:
            print(json.dumps({
                "error": "usage: face_mediapipe_worker.py <image_path> "
                         "[--with-emotions] [--with-geometry]"
            }))
            return 2

        image_path = args[0]
        flags = set(args[1:])
        with_emotions = "--with-emotions" in flags
        with_geometry = "--with-geometry" in flags

        image = load_image_file(image_path)
        encodings = face_encodings(image)
        payload = {
            "encodings": [encoding.tolist() for encoding in encodings],
        }
        if with_emotions:
            payload["emotions"] = face_emotions(image)
        if with_geometry:
            payload["geometry"] = [geom.tolist() for geom in face_geometry(image)]
        print(json.dumps(payload))
        return 0
    except Exception as exc:
        print(json.dumps({"error": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
