"""
Simple monitoring dashboard for Algosat Trading System.
Provides a web-based interface to monitor system health, performance, and trading metrics.
"""
import asyncio
import json
from datetime import datetime, timedelta
from typing import Dict, Any, List
from pathlib import Path

from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# Import our monitoring modules
from core.monitoring import TradingMetrics, HealthChecker
from core.security import SecurityManager
from core.resilience import ErrorTracker
from core.vps_performance import VPSOptimizer
from core.config_management import ConfigurationManager

# Dashboard app
dashboard_app = FastAPI(title="Algosat Monitoring Dashboard")

# Templates and static files
templates = Jinja2Templates(directory="templates")

class MonitoringDashboard:
    """Main monitoring dashboard class."""
    
    def __init__(self):
        self.health_checker = None
        self.trading_metrics = None
        self.security_manager = None
        self.error_tracker = None
        self.vps_optimizer = None
        self.config_manager = None
    
    async def initialize(self):
        """Initialize dashboard components."""
        self.health_checker = HealthChecker()
        self.trading_metrics = TradingMetrics()
        self.vps_optimizer = VPSOptimizer()
        self.config_manager = ConfigurationManager()
        
        await self.config_manager.initialize()
        
        config_dir = self.config_manager.config_dir
        self.security_manager = SecurityManager(
            config_file=config_dir / "security_config.yaml"
        )
        await self.security_manager.initialize()
        
        self.error_tracker = ErrorTracker(
            db_path=config_dir / "errors.db"
        )
        await self.error_tracker.initialize()
    
    async def get_dashboard_data(self) -> Dict[str, Any]:
        """Get comprehensive dashboard data."""
        try:
            # System health
            health_status = await self.health_checker.get_health_status()
            
            # VPS performance
            vps_metrics = await self.vps_optimizer.get_performance_metrics()
            
            # Security status
            security_status = await self.security_manager.get_security_status()
            recent_alerts = await self.security_manager.get_recent_alerts(limit=5)
            
            # Error tracking
            recent_errors = await self.error_tracker.get_recent_errors(limit=10)
            error_trends = await self.error_tracker.get_error_trends()
            
            # Trading metrics (placeholder - integrate with actual trading data)
            trading_status = {
                "active_strategies": 0,
                "open_positions": 0,
                "daily_pnl": 0.0,
                "total_trades_today": 0,
                "success_rate": 0.0
            }
            
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "system": {
                    "status": health_status["status"],
                    "uptime": self.health_checker.get_uptime(),
                    "components": {
                        "database": await self.health_checker.check_database(),
                        "api": True,  # If we're responding, API is up
                        "security": security_status.get("active", False),
                        "monitoring": True
                    }
                },
                "performance": {
                    "cpu_usage": vps_metrics.get("cpu_usage", 0),
                    "memory_usage": vps_metrics.get("memory_usage", 0),
                    "disk_usage": vps_metrics.get("disk_usage", 0),
                    "network_io": vps_metrics.get("network_io", {}),
                    "recommendations": await self.vps_optimizer.get_optimization_recommendations()
                },
                "security": {
                    "status": "active" if security_status.get("active") else "inactive",
                    "active_sessions": await self.security_manager.get_active_sessions_count(),
                    "recent_alerts": recent_alerts[:5],
                    "blocked_ips": len(await self.security_manager.get_blocked_ips()),
                    "failed_login_attempts": security_status.get("failed_attempts", 0)
                },
                "errors": {
                    "total_today": len([e for e in recent_errors if 
                                      datetime.fromisoformat(e.get("timestamp", "1970-01-01")) > 
                                      datetime.utcnow() - timedelta(days=1)]),
                    "recent_errors": recent_errors[:5],
                    "trends": error_trends,
                    "critical_errors": len([e for e in recent_errors if 
                                          e.get("severity") == "CRITICAL"])
                },
                "trading": trading_status
            }
        except Exception as e:
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "error": f"Failed to collect dashboard data: {str(e)}",
                "status": "error"
            }

# Global dashboard instance
dashboard = MonitoringDashboard()

@dashboard_app.on_event("startup")
async def startup_event():
    """Initialize dashboard on startup."""
    await dashboard.initialize()

@dashboard_app.get("/", response_class=HTMLResponse)
async def dashboard_home(request: Request):
    """Main dashboard page."""
    dashboard_data = await dashboard.get_dashboard_data()
    
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "data": dashboard_data,
            "page_title": "Algosat Monitoring Dashboard"
        }
    )

@dashboard_app.get("/api/data")
async def get_dashboard_data():
    """API endpoint for dashboard data (for AJAX updates)."""
    return await dashboard.get_dashboard_data()

@dashboard_app.get("/api/health")
async def health_status():
    """Health status API endpoint."""
    health_data = await dashboard.health_checker.get_health_status()
    return health_data

@dashboard_app.get("/api/performance")
async def performance_metrics():
    """Performance metrics API endpoint."""
    performance_data = await dashboard.vps_optimizer.get_performance_metrics()
    return performance_data

@dashboard_app.get("/api/security")
async def security_status():
    """Security status API endpoint."""
    security_data = {
        "status": await dashboard.security_manager.get_security_status(),
        "alerts": await dashboard.security_manager.get_recent_alerts(limit=10),
        "blocked_ips": await dashboard.security_manager.get_blocked_ips(),
        "active_sessions": await dashboard.security_manager.get_active_sessions_count()
    }
    return security_data

@dashboard_app.get("/api/errors")
async def error_status():
    """Error tracking API endpoint."""
    error_data = {
        "recent_errors": await dashboard.error_tracker.get_recent_errors(limit=20),
        "trends": await dashboard.error_tracker.get_error_trends(),
        "summary": await dashboard.error_tracker.get_error_summary()
    }
    return error_data

# HTML template for the dashboard
DASHBOARD_HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{page_title}}</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background-color: #f5f5f5;
            color: #333;
        }
        
        .header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 1rem 2rem;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        
        .header h1 {
            font-size: 1.8rem;
            font-weight: 300;
        }
        
        .timestamp {
            font-size: 0.9rem;
            opacity: 0.8;
        }
        
        .container {
            max-width: 1200px;
            margin: 0 auto;
            padding: 2rem;
        }
        
        .dashboard-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 1.5rem;
            margin-top: 1rem;
        }
        
        .card {
            background: white;
            border-radius: 8px;
            padding: 1.5rem;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            border-left: 4px solid #667eea;
        }
        
        .card h2 {
            font-size: 1.2rem;
            margin-bottom: 1rem;
            color: #333;
        }
        
        .status {
            display: inline-block;
            padding: 0.3rem 0.8rem;
            border-radius: 20px;
            font-size: 0.8rem;
            font-weight: bold;
            text-transform: uppercase;
        }
        
        .status.healthy {
            background-color: #d4edda;
            color: #155724;
        }
        
        .status.warning {
            background-color: #fff3cd;
            color: #856404;
        }
        
        .status.error {
            background-color: #f8d7da;
            color: #721c24;
        }
        
        .metric {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 0.5rem 0;
            border-bottom: 1px solid #eee;
        }
        
        .metric:last-child {
            border-bottom: none;
        }
        
        .metric-label {
            font-weight: 500;
        }
        
        .metric-value {
            font-size: 1.1rem;
            font-weight: bold;
            color: #667eea;
        }
        
        .progress-bar {
            width: 100%;
            height: 8px;
            background-color: #e0e0e0;
            border-radius: 4px;
            margin: 0.5rem 0;
            overflow: hidden;
        }
        
        .progress-fill {
            height: 100%;
            background: linear-gradient(90deg, #4CAF50, #45a049);
            border-radius: 4px;
            transition: width 0.3s ease;
        }
        
        .progress-fill.warning {
            background: linear-gradient(90deg, #ff9800, #f57c00);
        }
        
        .progress-fill.danger {
            background: linear-gradient(90deg, #f44336, #d32f2f);
        }
        
        .error-list {
            max-height: 200px;
            overflow-y: auto;
        }
        
        .error-item {
            padding: 0.5rem;
            margin: 0.5rem 0;
            background-color: #f8f9fa;
            border-left: 3px solid #dc3545;
            border-radius: 4px;
            font-size: 0.9rem;
        }
        
        .error-time {
            font-size: 0.8rem;
            color: #666;
        }
        
        .refresh-btn {
            position: fixed;
            bottom: 2rem;
            right: 2rem;
            background: #667eea;
            color: white;
            border: none;
            padding: 1rem;
            border-radius: 50%;
            cursor: pointer;
            box-shadow: 0 4px 12px rgba(0,0,0,0.2);
            transition: transform 0.2s ease;
        }
        
        .refresh-btn:hover {
            transform: scale(1.1);
        }
        
        .auto-refresh {
            font-size: 0.8rem;
            color: #666;
            text-align: center;
            margin-top: 1rem;
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>{{page_title}}</h1>
        <div class="timestamp">Last updated: <span id="timestamp">{{data.timestamp}}</span></div>
    </div>
    
    <div class="container">
        <div class="dashboard-grid">
            <!-- System Status Card -->
            <div class="card">
                <h2>System Status</h2>
                <div class="metric">
                    <span class="metric-label">Overall Status</span>
                    <span class="status {{data.system.status}}">{{data.system.status}}</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Uptime</span>
                    <span class="metric-value">{{data.system.uptime}}</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Database</span>
                    <span class="status {{'healthy' if data.system.components.database else 'error'}}">
                        {{'Online' if data.system.components.database else 'Offline'}}
                    </span>
                </div>
                <div class="metric">
                    <span class="metric-label">API</span>
                    <span class="status {{'healthy' if data.system.components.api else 'error'}}">
                        {{'Online' if data.system.components.api else 'Offline'}}
                    </span>
                </div>
                <div class="metric">
                    <span class="metric-label">Security</span>
                    <span class="status {{'healthy' if data.system.components.security else 'warning'}}">
                        {{'Active' if data.system.components.security else 'Inactive'}}
                    </span>
                </div>
            </div>
            
            <!-- Performance Card -->
            <div class="card">
                <h2>Performance Metrics</h2>
                <div class="metric">
                    <span class="metric-label">CPU Usage</span>
                    <span class="metric-value">{{data.performance.cpu_usage}}%</span>
                </div>
                <div class="progress-bar">
                    <div class="progress-fill {{'danger' if data.performance.cpu_usage > 80 else 'warning' if data.performance.cpu_usage > 60 else ''}}" 
                         style="width: {{data.performance.cpu_usage}}%"></div>
                </div>
                
                <div class="metric">
                    <span class="metric-label">Memory Usage</span>
                    <span class="metric-value">{{data.performance.memory_usage}}%</span>
                </div>
                <div class="progress-bar">
                    <div class="progress-fill {{'danger' if data.performance.memory_usage > 80 else 'warning' if data.performance.memory_usage > 60 else ''}}" 
                         style="width: {{data.performance.memory_usage}}%"></div>
                </div>
                
                <div class="metric">
                    <span class="metric-label">Disk Usage</span>
                    <span class="metric-value">{{data.performance.disk_usage}}%</span>
                </div>
                <div class="progress-bar">
                    <div class="progress-fill {{'danger' if data.performance.disk_usage > 80 else 'warning' if data.performance.disk_usage > 60 else ''}}" 
                         style="width: {{data.performance.disk_usage}}%"></div>
                </div>
            </div>
            
            <!-- Security Status Card -->
            <div class="card">
                <h2>Security Status</h2>
                <div class="metric">
                    <span class="metric-label">Security Status</span>
                    <span class="status {{'healthy' if data.security.status == 'active' else 'warning'}}">{{data.security.status}}</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Active Sessions</span>
                    <span class="metric-value">{{data.security.active_sessions}}</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Blocked IPs</span>
                    <span class="metric-value">{{data.security.blocked_ips}}</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Failed Logins</span>
                    <span class="metric-value">{{data.security.failed_login_attempts}}</span>
                </div>
                {% if data.security.recent_alerts %}
                <div style="margin-top: 1rem;">
                    <strong>Recent Alerts:</strong>
                    <div class="error-list">
                        {% for alert in data.security.recent_alerts %}
                        <div class="error-item">
                            <div>{{alert.message}}</div>
                            <div class="error-time">{{alert.timestamp}}</div>
                        </div>
                        {% endfor %}
                    </div>
                </div>
                {% endif %}
            </div>
            
            <!-- Error Tracking Card -->
            <div class="card">
                <h2>Error Tracking</h2>
                <div class="metric">
                    <span class="metric-label">Errors Today</span>
                    <span class="metric-value">{{data.errors.total_today}}</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Critical Errors</span>
                    <span class="metric-value">{{data.errors.critical_errors}}</span>
                </div>
                {% if data.errors.recent_errors %}
                <div style="margin-top: 1rem;">
                    <strong>Recent Errors:</strong>
                    <div class="error-list">
                        {% for error in data.errors.recent_errors %}
                        <div class="error-item">
                            <div><strong>{{error.error_type}}:</strong> {{error.message}}</div>
                            <div class="error-time">{{error.component}} - {{error.timestamp}}</div>
                        </div>
                        {% endfor %}
                    </div>
                </div>
                {% endif %}
            </div>
            
            <!-- Trading Status Card -->
            <div class="card">
                <h2>Trading Status</h2>
                <div class="metric">
                    <span class="metric-label">Active Strategies</span>
                    <span class="metric-value">{{data.trading.active_strategies}}</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Open Positions</span>
                    <span class="metric-value">{{data.trading.open_positions}}</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Daily P&L</span>
                    <span class="metric-value" style="color: {{'green' if data.trading.daily_pnl >= 0 else 'red'}}">
                        ₹{{data.trading.daily_pnl}}
                    </span>
                </div>
                <div class="metric">
                    <span class="metric-label">Trades Today</span>
                    <span class="metric-value">{{data.trading.total_trades_today}}</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Success Rate</span>
                    <span class="metric-value">{{data.trading.success_rate}}%</span>
                </div>
            </div>
        </div>
        
        <div class="auto-refresh">
            Auto-refresh every 30 seconds
        </div>
    </div>
    
    <button class="refresh-btn" onclick="refreshDashboard()">⟳</button>
    
    <script>
        async function refreshDashboard() {
            try {
                const response = await fetch('/api/data');
                const data = await response.json();
                
                // Update timestamp
                document.getElementById('timestamp').textContent = data.timestamp;
                
                // Reload the page with new data (simple approach)
                location.reload();
            } catch (error) {
                console.error('Failed to refresh dashboard:', error);
            }
        }
        
        // Auto-refresh every 30 seconds
        setInterval(refreshDashboard, 30000);
        
        // Update timestamp display
        function updateTimestamp() {
            const now = new Date();
            document.getElementById('timestamp').textContent = now.toISOString();
        }
        
        // Update timestamp every second
        setInterval(updateTimestamp, 1000);
    </script>
</body>
</html>
"""

# Create templates directory and save template
def create_dashboard_template():
    """Create dashboard template file."""
    templates_dir = Path("templates")
    templates_dir.mkdir(exist_ok=True)
    
    template_file = templates_dir / "dashboard.html"
    with open(template_file, 'w') as f:
        f.write(DASHBOARD_HTML_TEMPLATE)

if __name__ == "__main__":
    import uvicorn
    
    # Create template
    create_dashboard_template()
    
    # Run dashboard
    uvicorn.run(
        dashboard_app,
        host="0.0.0.0",
        port=8081,
        reload=False
    )
