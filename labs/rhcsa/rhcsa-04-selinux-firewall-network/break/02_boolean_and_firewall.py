"""httpd may not connect to the network; the firewall opened the wrong port."""


def apply(ctx):
    ctx.run(["setsebool", "-P", "httpd_can_network_connect", "off"], check=True)
    ctx.run(["firewall-cmd", "--permanent", "--add-port=8080/tcp"], check=True)
    ctx.run(["firewall-cmd", "--reload"], check=True)
