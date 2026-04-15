#!/usr/bin/env python3
"""
check_icon.py — Check if a PNG is suitable for use as a macOS template (tray) icon.

A valid template icon must have:
  - Only pure black pixels (R=G=B=0) where visible
  - Only fully opaque (alpha=255) or fully transparent (alpha=0) pixels
  - No semi-transparent or coloured pixels

Usage:
  python3 check_icon.py <path-to-icon.png>
"""

import struct
import sys
import zlib


def check_icon(path: str) -> None:
    with open(path, "rb") as f:
        data = f.read()

    # Collect all IDAT chunks
    idat = b""
    i = 8
    while i < len(data):
        length = struct.unpack(">I", data[i : i + 4])[0]
        chunk_type = data[i + 4 : i + 8]
        if chunk_type == b"IDAT":
            idat += data[i + 8 : i + 8 + length]
        i += 12 + length

    # Read image dimensions from IHDR
    ihdr_start = data.index(b"IHDR") + 4
    width, height = struct.unpack(">II", data[ihdr_start : ihdr_start + 8])
    print(f"Size: {width}x{height}")

    raw = zlib.decompress(idat)
    row_size = 1 + width * 4  # filter byte + RGBA per pixel

    non_binary_alpha = {}
    non_black = {}

    for row in range(height):
        base = row * row_size + 1
        for col in range(width):
            r = raw[base + col * 4]
            g = raw[base + col * 4 + 1]
            b = raw[base + col * 4 + 2]
            a = raw[base + col * 4 + 3]

            if a not in (0, 255):
                non_binary_alpha[(r, g, b, a)] = non_binary_alpha.get((r, g, b, a), 0) + 1
            if a == 255 and (r != 0 or g != 0 or b != 0):
                non_black[(r, g, b, a)] = non_black.get((r, g, b, a), 0) + 1

    total_bad_alpha = sum(non_binary_alpha.values())
    total_non_black = sum(non_black.values())

    if total_bad_alpha == 0 and total_non_black == 0:
        print("✓ Icon is valid for macOS template mode")
        return

    if total_bad_alpha:
        print(f"✗ Semi-transparent pixels: {total_bad_alpha} ({len(non_binary_alpha)} unique alpha values)")
        for px, count in sorted(non_binary_alpha.items(), key=lambda x: -x[1])[:5]:
            print(f"    RGBA{px}: {count}px")

    if total_non_black:
        print(f"✗ Non-black visible pixels: {total_non_black} ({len(non_black)} unique values)")
        for px, count in sorted(non_black.items(), key=lambda x: -x[1])[:5]:
            print(f"    RGBA{px}: {count}px")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <path-to-icon.png>")
        sys.exit(1)
    check_icon(sys.argv[1])
