#!/bin/bash
# Start script for Deriv Trading Bot V2

set -e

echo "🤖 Starting Deriv Trading Bot V2..."

# Check if .env exists
if [ ! -f .env ]; then
    echo "❌ Error: .env file not found"
    echo "Please create .env file with your credentials"
    exit 1
fi

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Error: Docker is not running"
    exit 1
fi

# Start Docker containers
echo "🐳 Starting Docker containers..."
docker-compose up -d

# Wait for PostgreSQL to be ready
echo "⏳ Waiting for PostgreSQL..."
sleep 10

# Check services health
echo "🏥 Checking service health..."
docker-compose ps

# Run bot
echo "🚀 Starting trading bot..."
docker-compose exec -d backend python -m app.bot

echo "✅ Bot started successfully!"
echo ""
echo "📊 View logs:"
echo "  docker-compose logs -f backend"
echo ""
echo "⏸️  Stop bot:"
echo "  docker-compose down"
