variable "sites" {
  type    = list(string)
  default = ["shop", "blog", "docs"]
}

resource "random_id" "cookie_secret" {
  count       = length(var.sites)
  byte_length = 16
}

resource "local_file" "vhost" {
  count    = length(var.sites)
  filename = "/etc/nginx-sites/${var.sites[count.index]}.conf"
  content = templatefile("${path.module}/vhost.conf.tftpl", {
    name   = var.sites[count.index]
    port   = 8100 + count.index
    secret = random_id.cookie_secret[count.index].hex
  })
  file_permission = "0644"
}
