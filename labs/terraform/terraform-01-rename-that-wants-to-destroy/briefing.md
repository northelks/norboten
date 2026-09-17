# The Rename That Wants to Destroy

`/srv/infra` is the Terraform configuration for the shop's local settings: a generated session key,
`/etc/shop/app.env` built from it, and the web server's site file `/etc/shop/nginx-site.conf`. Its
state is the local `terraform.tfstate` in the same directory.

A pull request renamed the resources to the names the team agreed on — `random_password.session_key`
and `local_file.app_env`. The first `terraform plan` after the merge wants to **destroy and recreate
the session key**, which would log out every customer. Nobody has applied it. The plan also wants to
replace the site file, which someone edited by hand on this machine during an incident.

What is expected, and graded:

1. `terraform plan` in `/srv/infra` reports no changes.
2. The session key is the one that exists today — in the state, under the new name, and in
   `/etc/shop/app.env`. The new resource names stay.
3. The state file, and any backup of it, can be read by root only.

Terraform's providers are already on the machine; there is no internet access. You have root through
`sudo`. Everything must still hold after a reboot.
