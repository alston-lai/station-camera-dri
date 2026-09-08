#!/bin/bash
pkill -f "start.command"
lsof -ti:5001 | xargs kill -9 2>/dev/null || true
open /Users/alston/Documents/LuxAI/station-camera-dri/start.command