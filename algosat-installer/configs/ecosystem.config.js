module.exports = {
  apps: [
    {
      name: "algosat-main",
      script: "/opt/algosat/.venv/bin/python",
      args: ["-m", "algosat.main"],
      cwd: "/opt/algosat/",
      interpreter: "none",
      instances: 1,
      exec_mode: "fork",
      autorestart: true,
      watch: false,
      max_memory_restart: "1G",
      env: {
        PYTHONPATH: "/opt/algosat",
        NODE_ENV: "production"
      },
      log_date_format: "YYYY-MM-DD HH:mm:ss Z",
      out_file: "/root/.pm2/logs/algosat-main-out.log",
      error_file: "/root/.pm2/logs/algosat-main-error.log",
      pid_file: "/root/.pm2/pids/algosat-main.pid",
      min_uptime: "10s",
      max_restarts: 10,
      restart_delay: 4000
    },
    {
      name: "algosat-api",
      script: "/opt/algosat/.venv/bin/uvicorn",
      args: ["algosat.api.enhanced_app:app", "--port", "8001", "--host", "0.0.0.0"],
      cwd: "/opt/algosat",
      interpreter: "/opt/algosat/.venv/bin/python",
      instances: 1,
      exec_mode: "fork",
      autorestart: true,
      watch: false,
      max_memory_restart: "512M",
      env: {
        PYTHONPATH: "/opt/algosat",
        NODE_ENV: "production"
      },
      log_date_format: "YYYY-MM-DD HH:mm:ss Z",
      out_file: "/opt/algosat/logs/pm2-algosat-api-out.log",
      error_file: "/opt/algosat/logs/pm2-algosat-api-error.log",
      pid_file: "/root/.pm2/pids/algosat-api.pid",
      min_uptime: "10s",
      max_restarts: 10,
      restart_delay: 4000
    },
    {
      name: "algosat-ui",
      script: "/usr/bin/npm",
      args: ["start"],
      cwd: "/opt/algosat/algosat-ui",
      interpreter: "/usr/bin/node",
      instances: 1,
      exec_mode: "fork",
      autorestart: true,
      watch: false,
      max_memory_restart: "256M",
      env: {
        NODE_ENV: "production",
        PORT: "3000"
      },
      log_date_format: "YYYY-MM-DD HH:mm:ss Z",
      out_file: "/opt/algosat/logs/pm2-algosat-ui-out.log",
      error_file: "/opt/algosat/logs/pm2-algosat-ui-error.log",
      pid_file: "/root/.pm2/pids/algosat-ui.pid",
      min_uptime: "10s",
      max_restarts: 10,
      restart_delay: 4000
    },
    {
      name: "broker-monitor",
      script: "/opt/algosat/.venv/bin/python",
      args: ["-m", "algosat.broker_monitor"],
      cwd: "/opt/algosat",
      interpreter: "none",
      instances: 1,
      exec_mode: "fork",
      autorestart: true,
      watch: false,
      max_memory_restart: "512M",
      env: {
        PYTHONPATH: "/opt/algosat",
        NODE_ENV: "production"
      },
      log_date_format: "YYYY-MM-DD HH:mm:ss Z",
      out_file: "/root/.pm2/logs/broker-monitor-out.log",
      error_file: "/root/.pm2/logs/broker-monitor-error.log",
      pid_file: "/root/.pm2/pids/broker-monitor.pid",
      min_uptime: "10s",
      max_restarts: 10,
      restart_delay: 4000
    }
  ]
};
