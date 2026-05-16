#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Isolierter Worker für MediaPipe-Bildverarbeitung."""

import json
import sys

from face_mediapipe import face_emotions, load_image_file, face_encodings


def main() -> int:
    try:
        if len(sys.argv) < 2 or len(sys.argv) > 3:
            print(json.dumps({"error": "usage: face_mediapipe_worker.py <image_path> [--with-emotions]"}))
            return 2

        image_path = sys.argv[1]
        with_emotions = len(sys.argv) == 3 and sys.argv[2] == "--with-emotions"
        image = load_image_file(image_path)
        encodings = face_encodings(image)
        payload = {
            "encodings": [encoding.tolist() for encoding in encodings],
        }
        if with_emotions:
            payload["emotions"] = face_emotions(image)
        print(json.dumps(payload))
        return 0
    except Exception as exc:
        print(json.dumps({"error": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
