#!/bin/bash
# InstaGet deploy script

RAW="https://raw.githubusercontent.com/stanize/Instaget/main"

echo "Stopping existing servers..."
pkill -f "python server.py" 2>/dev/null && echo "✓ Flask stopped" || echo "- Flask was not running"
pkill -f "http.server 8080" 2>/dev/null && echo "✓ HTTP server stopped" || echo "- HTTP server was not running"
sleep 1

echo "Downloading latest files..."
curl -s -o ~/server.py "$RAW/server.py" && echo "✓ server.py"
curl -s -o ~/index.html "$RAW/index.html" && echo "✓ index.html"

echo "Starting servers..."
nohup python ~/server.py > ~/server.log 2>&1 &
echo "✓ Flask started (port 5000)"
nohup python -m http.server 8080 --directory ~ > ~/http.log 2>&1 &
echo "✓ HTTP server started (port 8080)"

sleep 1
VERSION=$(curl -s http://localhost:5000/version 2>/dev/null)
echo "Done! $VERSION"
echo "Open http://localhost:8080 in Chrome"
