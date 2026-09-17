#!/bin/sh
set -eu
cd /srv/sites
export CHECKPOINT_DISABLE=1 TF_IN_AUTOMATION=1 TF_INPUT=0
cat > main.tf <<'HCL'
variable "sites" {
  description = "Each site and its port. Ports are explicit, so removing a site moves nothing."
  type        = map(object({ port = number }))
  default = {
    shop = { port = 8100 }
    docs = { port = 8102 }
  }
}

resource "random_id" "cookie_secret" {
  for_each    = var.sites
  byte_length = 16
}

resource "local_file" "vhost" {
  for_each = var.sites
  filename = "/etc/nginx-sites/${each.key}.conf"
  content = templatefile("${path.module}/vhost.conf.tftpl", {
    name   = each.key
    port   = each.value.port
    secret = random_id.cookie_secret[each.key].hex
  })
  file_permission = "0644"
}

# from positions to names: shop was [0], docs was [2]; the blog's [1] is destroyed
moved {
  from = random_id.cookie_secret[0]
  to   = random_id.cookie_secret["shop"]
}

moved {
  from = random_id.cookie_secret[2]
  to   = random_id.cookie_secret["docs"]
}

moved {
  from = local_file.vhost[0]
  to   = local_file.vhost["shop"]
}

moved {
  from = local_file.vhost[2]
  to   = local_file.vhost["docs"]
}
HCL
terraform apply -auto-approve
