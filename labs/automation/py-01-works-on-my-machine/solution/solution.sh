#!/bin/sh
set -eu
chown etl:etl /etc/etl/token
chmod 600 /etc/etl/token
chown -R etl:etl /var/lib/etl
mkdir -p /etc/systemd/system/etl-report.service.d
cat > /etc/systemd/system/etl-report.service.d/run.conf <<'UNIT'
[Service]
User=etl
WorkingDirectory=/opt/etl
ExecStart=
ExecStart=/opt/etl/.venv/bin/python /opt/etl/report.py
UNIT
systemctl daemon-reload
systemctl enable --now etl-report.timer
systemctl start etl-report.service
