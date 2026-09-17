variable "listen_port" {
  type    = number
  default = 8080
}

resource "random_password" "session_key" {
  length  = 32
  special = false
}

resource "local_file" "app_env" {
  filename        = "/etc/shop/app.env"
  content         = "SESSION_KEY=${random_password.session_key.result}\nLISTEN_PORT=${var.listen_port}\n"
  file_permission = "0600"
}

resource "local_file" "nginx_site" {
  filename        = "/etc/shop/nginx-site.conf"
  content         = templatefile("${path.module}/site.conf.tftpl", { port = var.listen_port })
  file_permission = "0644"
}
