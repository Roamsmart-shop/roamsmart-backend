#!/bin/bash

# deploy.sh - Production deployment script

echo "========================================="
echo "Roamsmart Digital Service Deployment"
echo "========================================="

# Set variables
APP_DIR="/var/www/roamsmart"
BACKUP_DIR="/var/backups/roamsmart"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# Create backup directory
mkdir -p $BACKUP_DIR

# Backup current database if exists
if [ -f "$APP_DIR/roamsmart.db" ]; then
    echo "📦 Backing up database..."
    cp $APP_DIR/roamsmart.db $BACKUP_DIR/roamsmart_db_$TIMESTAMP.db
fi

# Pull latest code
echo "📥 Pulling latest code..."
cd $APP_DIR
git pull origin main

# Activate virtual environment
echo "🐍 Activating virtual environment..."
source venv/bin/activate

# Install dependencies
echo "📦 Installing dependencies..."
pip install -r requirements.txt --no-cache-dir

# Run database migrations
echo "🗄️ Running database migrations..."
flask db upgrade

# Clear cache
echo "🗑️ Clearing cache..."
find . -type d -name "__pycache__" -exec rm -rf {} +
find . -type f -name "*.pyc" -delete

# Set permissions
echo "🔒 Setting permissions..."
chown -R www-data:www-data $APP_DIR
chmod -R 755 $APP_DIR

# Restart services
echo "🔄 Restarting services..."
sudo systemctl daemon-reload
sudo systemctl restart roamsmart
sudo systemctl restart nginx

# Check status
echo "✅ Deployment complete!"
sudo systemctl status roamsmart --no-pager

echo "========================================="
echo "Deployment completed at $TIMESTAMP"
echo "========================================="