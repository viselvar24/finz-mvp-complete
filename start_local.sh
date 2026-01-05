#!/bin/bash

# Perfient MVP - Local Development Startup Script

echo "🚀 Starting Perfient MVP in Mock Mode..."
echo ""

# Check if .env exists
if [ ! -f ".env" ]; then
    echo "⚠️  .env file not found. Creating from template..."
    echo "MOCK_MODE=true" > .env
    echo "TIINGO_API_KEY=12a4b6199b51d43953b990b9ec734b451e05d8e1" >> .env
    echo "✅ .env file created"
fi

# Check MOCK_MODE setting
if grep -q "MOCK_MODE=true" .env; then
    echo "✅ Mock Mode enabled - using dummy data (no Firestore)"
else
    echo "⚠️  Warning: MOCK_MODE is not set to 'true'"
    echo "   Set MOCK_MODE=true in .env for local development"
fi

echo ""
echo "📦 Checking Python environment..."

# Check if virtual environment exists, create if not
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
    if [ $? -ne 0 ]; then
        echo "❌ Failed to create virtual environment"
        echo "Make sure Python 3.8+ is installed"
        exit 1
    fi
    echo "✅ Virtual environment created"
fi

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate
if [ $? -ne 0 ]; then
    echo "❌ Failed to activate virtual environment"
    exit 1
fi

# Check if streamlit is installed
if ! python -c "import streamlit" 2>/dev/null; then
    echo "⚠️  Streamlit not found. Installing dependencies..."
    pip install -r requirements.txt
    if [ $? -ne 0 ]; then
        echo "❌ Failed to install dependencies"
        exit 1
    fi
    echo "✅ Dependencies installed"
fi

echo ""
echo "🌐 Starting Streamlit app..."
echo "   App will open at: http://localhost:8501"
echo ""
echo "💡 Tip: Keep this terminal open while using the app"
echo "   Press Ctrl+C to stop"
echo ""

cd "$(dirname "$0")"
python -m streamlit run app/Chat.py
