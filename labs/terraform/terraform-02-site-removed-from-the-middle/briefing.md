# The Site Removed From the Middle

`/srv/sites` is the Terraform configuration that generates one web-server virtual host per site into
`/etc/nginx-sites/`, each with its own port and its own cookie secret. Three sites have been live for
months: `shop` on 8100, `blog` on 8101 and `docs` on 8102.

The blog is being retired. Someone removed `"blog"` from the list of sites and ran `terraform plan`.
The plan wanted to rewrite `docs` with the blog's port and the blog's secret, and delete `docs.conf`
— so they stopped, and nothing has been applied.

What is expected, and graded:

1. `blog` is gone: no `blog.conf`, and nothing for the blog in the state.
2. `shop` and `docs` are exactly as they are now — same ports, same cookie secrets, same files — and
   `terraform plan` reports no changes.
3. Each site's resources are identified in the state by the site's name, so that the next site
   removed or added touches only that site.

Terraform's providers are already on the machine; there is no internet access. You have root through
`sudo`. Everything must still hold after a reboot.
