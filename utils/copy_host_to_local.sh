#!/bin/bash

# Configuration
REMOTE_HOST="root@65.108.157.27"
REMOTE_PATH="~/AI-SWE-Bench-Sota-SWE/outputs/*"
# REMOTE_PATH="~/AI-SWE-Bench-Sota-SWE/submissions/*"
LOCAL_PATH="outputs"
# LOCAL_PATH="submissions"

# Ensure local directory exists
mkdir -p "$LOCAL_PATH"

# Clear existing contents
echo "Clearing existing contents in $LOCAL_PATH..."
rm -rf "$LOCAL_PATH"/*

# Copy from remote
echo "Copying from remote server..."
if scp -r "$REMOTE_HOST:$REMOTE_PATH " "$LOCAL_PATH/"; then
    echo "Transfer completed successfully"
else
    echo "Transfer failed with exit code $?"
    exit 1
fi

# Optional: List contents to verify
echo -e "\nContents of $LOCAL_PATH after transfer:"
ls -la "$LOCAL_PATH"
