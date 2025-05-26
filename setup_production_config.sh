#!/bin/bash
"""
Setup production configuration for Algosat trading system.
This script creates the necessary configuration files with security tokens.
"""

# Set production environment variables
export ALGOSAT_MASTER_KEY="$(openssl rand -base64 32)"
export JWT_SECRET="$(openssl rand -base64 64)"
export DB_PASSWORD="$(openssl rand -base64 24)"

# Create configuration directory
CONFIG_DIR="/opt/algosat/config"
mkdir -p "$CONFIG_DIR"

echo "Creating production configuration..."

# Generate environment file
cat > "$CONFIG_DIR/.env" << EOF
# Algosat Production Configuration
ALGOSAT_MASTER_KEY=$ALGOSAT_MASTER_KEY
JWT_SECRET=$JWT_SECRET

# Database Configuration
DB_HOST=localhost
DB_PORT=5432
DB_NAME=algosat_db
DB_USER=algosat_user
DB_PASSWORD=$DB_PASSWORD

# Security Configuration
ENABLE_IP_WHITELIST=false
IP_WHITELIST=127.0.0.1,localhost

# Monitoring Configuration
LOG_LEVEL=INFO
ALERT_EMAIL=admin@yourcompany.com

# Trading Configuration
PAPER_TRADING=false
EOF

echo "✓ Environment configuration created at $CONFIG_DIR/.env"

# Set secure permissions
chmod 600 "$CONFIG_DIR/.env"

# Create broker configuration template
cat > "$CONFIG_DIR/brokers.yaml" << EOF
brokers:
  zerodha:
    enabled: false
    api_key: ""
    api_secret: ""
    api_token: ""
    base_url: "https://api.kite.trade"
    timeout_seconds: 30
    test_mode: false
  
  fyers:
    enabled: false
    api_key: ""
    api_secret: ""
    api_token: ""
    base_url: "https://api-t1.fyers.in"
    timeout_seconds: 30
    test_mode: false
EOF

echo "✓ Broker configuration template created at $CONFIG_DIR/brokers.yaml"
chmod 600 "$CONFIG_DIR/brokers.yaml"

echo ""
echo "🔐 IMPORTANT SECURITY INFORMATION:"
echo "=================================================="
echo "Master Key: $ALGOSAT_MASTER_KEY"
echo "JWT Secret: $JWT_SECRET"
echo "DB Password: $DB_PASSWORD"
echo "=================================================="
echo ""
echo "⚠️  Store these values securely! They are required for system operation."
echo "✅ Production configuration setup complete!"
echo ""
echo "Next steps:"
echo "1. Update broker credentials in $CONFIG_DIR/brokers.yaml"
echo "2. Run the deployment script: ./deploy/production_deploy.sh"
echo "3. Configure SSL certificates for production use"
