# AlgoSat Trading Bot - User Guide

## Overview

**AlgoSat** is an advanced automated trading platform that connects to multiple brokers simultaneously, executes trading strategies, and manages your portfolio in real-time. The system operates 24/7 during market hours, making intelligent trading decisions based on your configured strategies.

---

## Key Features

### 🔄 **Multi-Broker Support**
- **Simultaneous Connections**: Connect to multiple brokers (Zerodha, Fyers, Angel One, etc.) at once
- **Real-Time Data**: Live market data streaming from your preferred broker
- **Cross-Broker Trading**: Execute trades across different broker accounts
- **Balance Monitoring**: Track account balances, available funds, and margin usage across all brokers

### 📊 **Automated Trading Strategies**
- **Pre-Built Strategies**: Ready-to-use trading algorithms for different market conditions
- **Strategy Customization**: Adjust parameters like lot size, stop loss, target profit
- **Risk Management**: Built-in risk controls to protect your capital
- **Market Hours Awareness**: Automatically starts/stops trading based on market timings

### 📈 **Real-Time Dashboard**
- **Performance Overview**: Live P&L tracking with interactive charts
- **Order Management**: Monitor all orders, executions, and trade history
- **Portfolio Summary**: Complete view of positions, balances, and performance metrics
- **Risk Analytics**: Sharpe ratio, max drawdown, daily returns, and best/worst days

### 🛡️ **Risk Management**
- **Position Limits**: Set maximum position sizes per strategy
- **Daily Loss Limits**: Automatic stop-trading when daily loss limits are reached
- **Emergency Controls**: One-click buttons to stop all strategies or exit all positions
- **Broker-Level Limits**: Individual risk limits for each connected broker

---

## Dashboard Overview

### **Main Navigation Tabs**

#### 1. **Overview Tab**
- **Live Statistics**: Current positions, overall P&L, today's performance
- **Performance Chart**: Visual representation of your trading performance over time
- **Risk Metrics**: Key performance indicators displayed in an easy-to-understand format
- **Emergency Controls**: Quick access to stop all trading or exit positions

#### 2. **Strategies Tab**
- **Strategy Management**: View, enable/disable trading strategies
- **Performance Tracking**: Per-strategy P&L and statistics
- **Configuration**: Adjust strategy parameters and risk settings
- **Symbol Management**: Control which stocks/instruments each strategy trades

#### 3. **Brokers Tab**
- **Broker Status**: Connection status and authentication details
- **Account Balances**: Real-time balance information for each broker
- **Risk Limits**: Set and monitor broker-specific trading limits
- **Configuration**: Manage broker credentials and settings

#### 4. **Orders Tab**
- **Order History**: Complete record of all executed trades
- **Live Orders**: Real-time view of pending and executed orders
- **P&L Analysis**: Daily and cumulative profit/loss charts
- **Export Function**: Download order history for record-keeping

#### 5. **Health Tab**
- **System Status**: Monitor system performance and connectivity
- **Error Logs**: View any issues or warnings
- **Performance Metrics**: System uptime and response times

---

## Key Functionalities

### **Trading Operations**

#### **Automatic Trading**
- Strategies run continuously during market hours
- Real-time decision making based on market conditions
- Automatic order placement and management
- Position sizing based on available capital and risk limits

#### **Manual Controls**
- **Emergency Stop**: Immediately disable all strategies and stop new trades
- **Exit All Positions**: Close all open positions across all brokers
- **Strategy Toggle**: Enable/disable individual strategies as needed
- **Broker Control**: Enable/disable trading on specific brokers

### **Performance Monitoring**

#### **Real-Time Metrics**
- **Current P&L**: Live profit/loss across all positions
- **Daily Performance**: Today's trading results
- **Historical Performance**: Long-term trading statistics
- **Risk Analytics**: Drawdown analysis, win rate, average returns

#### **Visual Analytics**
- **Performance Charts**: Color-coded charts (green for profits, red for losses)
- **Interactive Graphs**: Hover over data points for detailed information
- **Multiple Timeframes**: Daily, weekly, and monthly performance views

### **Risk Management Tools**

#### **Automated Risk Controls**
- **Position Limits**: Maximum number of positions per strategy
- **Loss Limits**: Daily maximum loss thresholds
- **Margin Monitoring**: Automatic position reduction if margin is low
- **Time-Based Controls**: Trading only during specified hours

#### **Manual Risk Controls**
- **Emergency Stop Button**: Instantly halt all trading activities
- **Individual Strategy Control**: Disable specific strategies if needed
- **Broker-Level Controls**: Stop trading on problematic brokers
- **Position Exit**: Manual closure of specific positions

---

## User Interface Features

### **Dashboard Elements**

#### **Status Indicators**
- **Green Indicators**: Active connections, profitable positions, running strategies
- **Red Indicators**: Disconnected brokers, losing positions, stopped strategies
- **Blue Indicators**: Data feeds, pending orders, neutral states
- **Animated Elements**: Live data updates, connection status pulses

#### **Interactive Components**
- **Expandable Order Details**: Click on orders to see execution details
- **Broker Execution Breakdown**: View entry/exit prices and broker-specific P&L
- **Chart Interactions**: Hover over charts for detailed data points
- **Real-Time Updates**: Data refreshes automatically every few seconds

#### **Color-Coded Information**
- **Profit/Loss Colors**: Green for positive, red for negative values
- **Status Colors**: Different colors for various order and strategy states
- **Risk Level Colors**: Visual indication of risk levels (low, medium, high)

### **Data Export & Analysis**
- **Order Export**: Download complete trading history in Excel format
- **Performance Reports**: Generate detailed performance summaries
- **Risk Analysis**: Export risk metrics and drawdown analysis
- **Profit/Loss Statements**: Ready-to-use P&L reports for tax purposes

---

## System Management

### **Starting the System**

#### **Complete System Start**
```bash
# Navigate to the AlgoSat directory
cd /opt/algosat

# Start all services
pm2 start ecosystem.config.js

# Check if all services are running
pm2 status
```

#### **Individual Service Management**
```bash
# Start specific services
pm2 start algosat-api      # Backend API
pm2 start algosat-ui       # Web Interface
pm2 start broker-monitor   # Broker Connection Monitor
pm2 start algosat-main     # Main Trading Engine

# Restart services
pm2 restart algosat-api
pm2 restart all            # Restart everything
```

### **Stopping the System**

#### **Emergency Stop (Trading Only)**
- Use the **"Emergency Stop"** button in the dashboard
- This stops all trading but keeps the system monitoring active

#### **Complete System Stop**
```bash
# Stop all services
pm2 stop all

# Stop specific service
pm2 stop algosat-main     # Stops trading engine only
```

### **System Monitoring**

#### **Service Status Check**
```bash
# View all running services
pm2 status

# View detailed information about a service
pm2 show algosat-main

# Monitor real-time performance
pm2 monit
```

#### **Log Monitoring**
```bash
# View recent logs for all services
pm2 logs

# View logs for specific service
pm2 logs algosat-main
pm2 logs algosat-api
pm2 logs broker-monitor

# View last 50 lines of logs
pm2 logs --lines 50

# Follow logs in real-time
pm2 logs algosat-main --lines 0
```

### **Log File Locations**
- **Main Trading Engine**: `/root/.pm2/logs/algosat-main-out.log`
- **API Backend**: `/root/.pm2/logs/algosat-api-out.log`
- **Broker Monitor**: `/root/.pm2/logs/broker-monitor-out.log`
- **Web Interface**: `/root/.pm2/logs/algosat-ui-out.log`
- **Error Logs**: `/root/.pm2/logs/[service-name]-error.log`

### **System Restart Procedures**

#### **After System Reboot**
```bash
# The system should auto-start, but if not:
cd /opt/algosat
pm2 resurrect
pm2 status
```

#### **After Configuration Changes**
```bash
# Restart specific services after changes
pm2 restart algosat-main    # After strategy changes
pm2 restart algosat-api     # After API changes
pm2 restart broker-monitor  # After broker credential changes
```

#### **Complete System Reset**
```bash
# Stop everything
pm2 stop all

# Start everything fresh
pm2 start ecosystem.config.js

# Save the configuration
pm2 save
```

### **Troubleshooting Quick Commands**

#### **Check System Health**
```bash
# Quick health check
pm2 status
pm2 logs --lines 10

# Check if services are responding
curl http://82.25.109.188:8000/health    # API health
curl http://82.25.109.188:3000           # UI health
```

#### **Common Issues**
- **Service Not Starting**: Check logs with `pm2 logs [service-name]`
- **UI Not Accessible**: Ensure algosat-ui is running on port 3000
- **API Not Responding**: Check algosat-api is running on port 8000
- **No Trading Activity**: Verify algosat-main service is active and strategies are enabled

---

## Access Information

- **Web Dashboard**: `http://82.25.109.188:3000` (or your server IP:3000)
- **API Endpoint**: `http://82.25.109.188:8000` (for advanced integrations)
- **Default Market Hours**: 9:15 AM to 3:30 PM (Indian Stock Market)

---

## Support & Maintenance

### **Regular Monitoring**
- Check system status daily using `pm2 status`
- Monitor log files for any error messages
- Review trading performance through the dashboard
- Verify broker connections are active

### **Backup Recommendations**
- Regularly export trading data from the dashboard
- Keep backups of strategy configurations
- Save broker credential configurations securely

### **Best Practices**
- Always use the Emergency Stop feature before system maintenance
- Monitor risk limits and adjust based on market conditions
- Keep the system updated and restart services periodically
- Review and analyze trading performance regularly

---

**Note**: This system operates with real money in live markets. Always monitor your positions and use appropriate risk management. The emergency controls are provided for your safety - use them when in doubt.

**Last Updated**: July 2025
