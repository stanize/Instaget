#!/bin/bash
# InstaGet status check

echo "================================"
echo "  InstaGet Status"
echo "================================"

# Flask server
FLASK_PID=$(pgrep -f "python server.py")
if [ -n "$FLASK_PID" ]; then
  echo "✓ Flask server    running (PID $FLASK_PID)"
  VERSION=$(curl -s --max-time 2 http://localhost:5000/version 2>/dev/null)
  if [ -n "$VERSION" ]; then
    echo "  Version:        $VERSION"
  else
    echo "  Version:        (not responding)"
  fi
else
  echo "✗ Flask server    NOT running"
fi

# HTTP server
HTTP_PID=$(pgrep -f "http.server 8080")
if [ -n "$HTTP_PID" ]; then
  echo "✓ HTTP server     running (PID $HTTP_PID)"
else
  echo "✗ HTTP server     NOT running"
fi

echo "--------------------------------"

# Downloads folder
DOWNLOAD_DIR=~/storage/downloads/InstaGet
if [ -d "$DOWNLOAD_DIR" ]; then
  VIDEO_COUNT=$(ls "$DOWNLOAD_DIR"/*.mp4 "$DOWNLOAD_DIR"/*.mkv "$DOWNLOAD_DIR"/*.webm 2>/dev/null | wc -l)
  COMP_COUNT=$(ls "$DOWNLOAD_DIR/compilations"/*.mp4 2>/dev/null | wc -l)
  FOLDER_SIZE=$(du -sh "$DOWNLOAD_DIR" 2>/dev/null | cut -f1)
  echo "📁 Downloads:     $VIDEO_COUNT video(s)"
  echo "🎞  Compilations:  $COMP_COUNT video(s)"
  echo "💾 Total size:    $FOLDER_SIZE"
else
  echo "📁 Downloads folder not found"
fi

echo "--------------------------------"

# Last server log lines
if [ -f ~/server.log ]; then
  echo "📋 Last server log:"
  tail -5 ~/server.log
fi

echo "================================"
