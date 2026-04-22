#!/bin/bash

echo "Installing dependencies..."
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

echo ""
echo "Starting bot..."
python -m src.bot.main
