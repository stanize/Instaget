#!/bin/bash
# InstaGet deploy script
# Run this in Termux to update to the latest version

RAW="https://raw.githubusercontent.com/stanize/instaget/main"

echo "Downloading latest files..."
curl -s -o ~/server.py "$RAW/server.py" && echo "✓ server.py"
curl -s -o ~/index.html "$RAW/index.html" && echo "✓ index.html"

echo "Restarting server..."
pkill -f "python server.py" 2>/dev/null
sleep 1
nohup python ~/server.py > ~/server.log 2>&1 &
sleep 1

echo "Done! Server running. Check version at http://localhost:5000/version"
