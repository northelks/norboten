#!/bin/sh
set -eu
semanage fcontext -a -t httpd_sys_content_t '/srv/status(/.*)?'
restorecon -R /srv/status
semanage port -a -t http_port_t -p tcp 8090
setsebool -P httpd_can_network_connect on
firewall-cmd --permanent --add-port=8090/tcp
firewall-cmd --reload
hostnamectl set-hostname web01.lab.example
con=$(nmcli -g GENERAL.CONNECTION device show eth0)
nmcli connection modify "$con" +ipv4.addresses 192.168.5.50/24
nmcli device reapply eth0
systemctl restart nginx
