#!/bin/bash
# Startup script for main.py in container

cd /ultralytics/workspace/smart-trash-can

# Source bashrc to load venv
if [ -f ~/.bashrc ]; then
    source ~/.bashrc
fi

# Run main.py
python3 -u main.py
