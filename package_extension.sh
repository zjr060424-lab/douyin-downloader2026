#!/bin/bash
# Package the browser extension into a zip file for distribution.

EXT_DIR="$(cd "$(dirname "$0")" && pwd)/extension"
OUTPUT="$(cd "$(dirname "$0")" && pwd)/extension.zip"

if [ ! -d "$EXT_DIR" ]; then
    echo "Error: extension/ directory not found"
    exit 1
fi

cd "$EXT_DIR"
rm -f "$OUTPUT"

echo "Packaging extension..."
zip -r "$OUTPUT" . -x "*.git*" "*.DS_Store" "__pycache__/*"

if [ -f "$OUTPUT" ]; then
    SIZE=$(du -h "$OUTPUT" | cut -f1)
    echo "Done: $OUTPUT ($SIZE)"
else
    echo "Error: failed to create zip"
    exit 1
fi
