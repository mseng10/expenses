#!/bin/bash

# Script to set up a Python virtual environment and install dependencies

VENV_NAME="venv"

# Check if Python 3 is installed
if ! command -v python3 &> /dev/null
then
    echo "Python 3 could not be found. Please install Python 3."
    exit 1
fi

# Check if pip is installed for Python 3
if ! python3 -m pip --version &> /dev/null
then
    echo "pip for Python 3 could not be found. Please ensure pip is installed."
    exit 1
fi

# Create virtual environment
if [ ! -d "$VENV_NAME" ]; then
    echo "Creating virtual environment '$VENV_NAME'..."
    python3 -m venv $VENV_NAME
    if [ $? -ne 0 ]; then
        echo "Failed to create virtual environment."
        exit 1
    fi
else
    echo "Virtual environment '$VENV_NAME' already exists."
fi

# Activate virtual environment and install requirements
echo "Activating virtual environment and installing dependencies from requirements.txt..."
source $VENV_NAME/bin/activate

pip install -r requirements.txt
if [ $? -ne 0 ]; then
    echo "Failed to install requirements."
    exit 1
fi

echo ""
echo "Setup complete."
echo "To activate the virtual environment for your current session, run: source $VENV_NAME/bin/activate"
echo "To deactivate, run: deactivate"
echo "After activation, you can run the server with: python app.py"