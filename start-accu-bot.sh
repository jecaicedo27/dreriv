#!/bin/bash
# ====================================
# Start Accumulator Bot (Boom 1000)
# Completely separate from the Rise/Fall bot
# ====================================
set -e

echo "🎰 Starting Accumulator Bot for Boom 1000..."

cd /var/www/jhonk/dreriv

# Run inside Docker container
docker exec -d deriv-backend python -m app.accu_bot

echo "✅ Accumulator Bot started in background (inside deriv-backend container)"
echo "📋 View logs: docker logs deriv-backend -f --tail 50"
echo "⏹️  Stop: docker exec deriv-backend pkill -f 'app.accu_bot'"
