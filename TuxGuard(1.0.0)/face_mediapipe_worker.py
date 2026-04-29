#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Isolierter Worker für MediaPipe-Bildverarbeitung."""

import json
import sys

from face_mediapipe import load_image_file, face_encodings


def main() -> int:
    try:
        if len(sys.argv) != 2:
            print(json.dumps({"error": "image path required"}))
            return 2

        image_path = sys.argv[1]
        image = load_image_file(image_path)
        encodings = face_encodings(image)
        print(json.dumps({"encodings": [encoding.tolist() for encoding in encodings]}))
        return 0
    except Exception as exc:
        print(json.dumps({"error": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
