---
title: count numbers things; for_each names them
topics: [terraform, networking]
minutes: 40
---

Three virtual hosts, one list: `sites = ["shop", "blog", "docs"]`. Terraform creates a configuration
file and a cookie secret for each, and derives each site's port from its position — 8100, 8101, 8102.
It has worked for months. Then the blog is retired, `"blog"` is taken out of the middle of the list, and
the plan wants to rewrite `docs` with the blog's port and the blog's secret, and to delete `docs.conf`.
The engineer who ran the plan stopped, correctly, and nothing was applied.

The plan was not wrong. With `count`, Terraform does not know the instances as `shop`, `blog` and `docs`.
It knows them as `[0]`, `[1]` and `[2]`, and the list only supplies what each index should look like
right now. Remove the element at index 1 and `docs` becomes index 1: the resource at `[1]` must change
from the blog to the docs site, and `[2]` has nothing left to describe. Everything derived from the index
— the port, the secret it was paired with — moves with it.

`for_each` over a map gives each instance a **key** instead of a position. Removing `blog` then removes
exactly the instances keyed `"blog"` and touches nothing else. Converting an existing `count` resource
to `for_each` is a refactoring, and like every refactoring in Terraform it needs `moved` blocks, so the
live objects keep their identity under their new addresses.

## What you should be able to do after this

- Explain how `count` and `for_each` address their instances, and why removing an element from the
  middle of a `count` list shifts everything after it.
- Read a plan that says `must be replaced`, `index [2] is out of range for count` or `resource does not
  use count`, and predict what apply would do.
- Convert a `count` resource to `for_each` over a map without replacing live instances, using `moved`
  blocks from indexes to keys.
- Keep values stable by naming them explicitly (a port per site) rather than deriving them from a
  position.
- Check a configuration change with `terraform fmt`, `validate` and a plan before applying, and prove
  the result with `-detailed-exitcode`.

## The mechanism

### How `count` addresses instances

```hcl
resource "local_file" "vhost" {
  count    = length(var.sites)
  filename = "/etc/nginx-sites/${var.sites[count.index]}.conf"
  content = templatefile("${path.module}/vhost.conf.tftpl", {
    name   = var.sites[count.index]
    port   = 8100 + count.index
    secret = random_id.cookie_secret[count.index].hex
  })
}
```

`count = 3` creates `local_file.vhost[0]`, `[1]` and `[2]`. The only identity an instance has is its
index; what the index *means* comes from the list at plan time. With `["shop", "blog", "docs"]`:

| Address | name | port | secret |
|---|---|---|---|
| `vhost[0]` / `cookie_secret[0]` | shop | 8100 | secret 0 |
| `vhost[1]` / `cookie_secret[1]` | blog | 8101 | secret 1 |
| `vhost[2]` / `cookie_secret[2]` | docs | 8102 | secret 2 |

After removing `"blog"`, `length` is 2 and the list is `["shop", "docs"]`:

| Address | wants to describe | consequence |
|---|---|---|
| `vhost[0]` | shop, 8100, secret 0 | unchanged |
| `vhost[1]` | docs, **8101**, **secret 1** | the blog's file becomes the docs file, with the blog's port and secret |
| `vhost[2]` | nothing — index out of range | destroyed, deleting `docs.conf` |
| `cookie_secret[1]` | kept | docs inherits the blog's secret |
| `cookie_secret[2]` | nothing | destroyed: docs's real secret is gone |

That is why `count` is the right tool only for **identical, interchangeable** instances — "three worker
VMs", where it does not matter which one disappears — and the wrong tool for a collection of named
things.

### How `for_each` addresses instances

```hcl
variable "sites" {
  type = map(object({ port = number }))
  default = {
    shop = { port = 8100 }
    docs = { port = 8102 }
  }
}

resource "local_file" "vhost" {
  for_each = var.sites
  filename = "/etc/nginx-sites/${each.key}.conf"
  content = templatefile("${path.module}/vhost.conf.tftpl", {
    name   = each.key
    port   = each.value.port
    secret = random_id.cookie_secret[each.key].hex
  })
}
```

Instances are `local_file.vhost["shop"]` and `local_file.vhost["docs"]`. `each.key` is the map key,
`each.value` the value. Keys are the identity: adding, removing or reordering entries affects only the
instances whose keys changed. A `set(string)` works too (`toset(var.names)`), with `each.key` and
`each.value` both the element.

Two design choices come with it:

- **Name the values that must not move.** The port was `8100 + count.index`, a value derived from a
  position. With `for_each` there is no position, so the port becomes explicit data: `docs` keeps 8102
  even though it is now the second of two sites.
- **Key related resources the same way.** `random_id.cookie_secret[each.key]` ties each site's secret
  to its site by name, not by coincidence of order.

`for_each` keys must be known at plan time — they cannot come from attributes that only exist after
apply (a resource's generated ID, for instance). Static names from variables are exactly right.

### Converting without replacing: moved blocks

Changing `count` to `for_each` changes every address: `[0]` is not `["shop"]`. Without help, the plan
would destroy all the index-addressed instances and create key-addressed ones — new files, and new
random secrets. `moved` blocks connect them:

```hcl
moved {
  from = random_id.cookie_secret[0]
  to   = random_id.cookie_secret["shop"]
}

moved {
  from = random_id.cookie_secret[2]
  to   = random_id.cookie_secret["docs"]
}
```

…and the same two for `local_file.vhost`. There is no move for `[1]`: the blog is being retired, so its
instances are left at an address the configuration no longer has, and the plan destroys them — which is
the only change anyone wanted. Moves are declared per instance, for every resource that uses the
collection; forgetting the `random_id` moves would keep the files and still regenerate the secrets.

The same thing can be done with `terraform state mv 'local_file.vhost[0]' 'local_file.vhost["shop"]'`
(note the quoting), but `moved` blocks are reviewed with the change and show up in the plan.

### Reading the plan

| Plan text | Meaning here |
|---|---|
| `local_file.vhost[1] must be replaced` with `filename … # forces replacement` | index 1 now describes a different file; `local_file` cannot rename a file in place |
| `(because index [2] is out of range for count)` | the list got shorter; the last index has nothing to describe |
| `(because resource does not use count)` | an index address remains after switching to `for_each`, and no `moved` claims it |
| `has moved to` | a `moved` block matched |
| `(because key ["shop"] is not in for_each map)` | a key was removed from the map |

`Plan: 0 to add, 0 to change, 2 to destroy` after the rewrite is the target: two destroys, both for the
blog.

### Checking a change before applying it

- `terraform fmt -check` fails on files that are not in canonical format — cheap, and catches stray
  edits.
- `terraform validate` checks syntax, references and types without touching state or providers'
  APIs — a mistyped `each.value.prot` fails here.
- `terraform plan` shows what apply would do; read every `destroy`.
- After applying, `terraform plan -detailed-exitcode` exits 0 when the configuration and reality agree.

A plan with a `-var` override is a safe way to rehearse the *next* change: what would removing `shop`
do? With `for_each`, the answer names only `shop`.

## A failure, walked through

Replayed on the track's lab VM before its image moved to Ubuntu 26.04; the output below is what
the machine printed.

**1. See what is live, and keep a copy of what must not change.**

```console
$ ls /etc/nginx-sites; grep -h -E 'listen|cookie_secret' /etc/nginx-sites/*.conf
blog.conf
docs.conf
shop.conf
    listen 8101;
    set $cookie_secret "535bb0ff9b932fee525e0febc9a99821";
    listen 8102;
    set $cookie_secret "42d96e5fae1eab423461668c6d0d5b87";
    listen 8100;
    set $cookie_secret "71308859d4fec3c48cd160e3b0bb4272";
$ cd /srv/sites && sudo terraform state list
local_file.vhost[0]
local_file.vhost[1]
local_file.vhost[2]
random_id.cookie_secret[0]
random_id.cookie_secret[1]
random_id.cookie_secret[2]
$ sudo cp /etc/nginx-sites/docs.conf /etc/nginx-sites/shop.conf /tmp/ && sudo chmod 644 /tmp/docs.conf /tmp/shop.conf
```

The files are listed alphabetically, so the `grep` output is blog, docs, shop: docs listens on 8102 with
secret `42d96e5f…`. The state knows the instances only by index.

**2. Read the configuration and the plan** (filtered to the decisive lines):

```console
$ cat /srv/sites/main.tf
variable "sites" {
  type    = list(string)
  default = ["shop", "docs"]
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
$ cd /srv/sites && sudo env CHECKPOINT_DISABLE=1 terraform plan -no-color 2>&1 | grep -E '^  # |^Plan:|filename|listen|cookie_secret|forces replacement'
random_id.cookie_secret[1]: Refreshing state... [id=U1uw_5uTL-5SXg_ryamYIQ]
random_id.cookie_secret[2]: Refreshing state... [id=QtluX64eq0I0YWaMbQ1bhw]
random_id.cookie_secret[0]: Refreshing state... [id=cTCIWdT-w8SM0WDjsLtCcg]
  # local_file.vhost[1] must be replaced
      ~ content              = <<-EOT # forces replacement
                listen 8101;
                set $cookie_secret "535bb0ff9b932fee525e0febc9a99821";
      ~ filename             = "/etc/nginx-sites/blog.conf" -> "/etc/nginx-sites/docs.conf" # forces replacement
  # local_file.vhost[2] will be destroyed
  # (because index [2] is out of range for count)
                listen 8102;
                set $cookie_secret "42d96e5fae1eab423461668c6d0d5b87";
      - filename             = "/etc/nginx-sites/docs.conf" -> null
  # random_id.cookie_secret[2] will be destroyed
  # (because index [2] is out of range for count)
  - resource "random_id" "cookie_secret" {
Plan: 1 to add, 0 to change, 3 to destroy.
```

Exactly the shift predicted: `vhost[1]` would turn `blog.conf` into `docs.conf` with port 8101 and the
blog's secret `535bb0ff…`, `vhost[2]` — the real `docs.conf` with 8102 — would be destroyed, and docs's
secret with it.

**3. Rewrite the configuration with named sites, explicit ports and moves.** `/srv/sites/main.tf`:

```hcl
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
```

```console
$ cd /srv/sites && sudo env CHECKPOINT_DISABLE=1 terraform fmt -check && sudo env CHECKPOINT_DISABLE=1 terraform validate -no-color
Success! The configuration is valid.
$ cd /srv/sites && sudo env CHECKPOINT_DISABLE=1 terraform plan -no-color 2>&1 | grep -E '^  # |^Plan:'
  # local_file.vhost[1] will be destroyed
  # (because resource does not use count)
  # local_file.vhost[2] has moved to local_file.vhost["docs"]
  # local_file.vhost[0] has moved to local_file.vhost["shop"]
  # random_id.cookie_secret[1] will be destroyed
  # (because resource does not use count)
  # random_id.cookie_secret[2] has moved to random_id.cookie_secret["docs"]
  # random_id.cookie_secret[0] has moved to random_id.cookie_secret["shop"]
Plan: 0 to add, 0 to change, 2 to destroy.
```

Four moves, and the only two destroys are index `[1]` — the blog.

**4. Apply, and prove nothing else changed.**

```console
$ cd /srv/sites && sudo env CHECKPOINT_DISABLE=1 terraform apply -auto-approve -no-color 2>&1 | grep -E 'Destroying|Destruction complete|Creating|Creation complete|^Apply complete'
local_file.vhost[1]: Destroying... [id=b43f6bd102757fe86bc5423cd68a64ee450ce75e]
local_file.vhost[1]: Destruction complete after 0s
random_id.cookie_secret[1]: Destroying... [id=U1uw_5uTL-5SXg_ryamYIQ]
random_id.cookie_secret[1]: Destruction complete after 0s
Apply complete! Resources: 0 added, 0 changed, 2 destroyed.
$ cd /srv/sites && sudo env CHECKPOINT_DISABLE=1 terraform plan -detailed-exitcode -no-color 2>&1 | tail -n 2; echo "exit=${PIPESTATUS[0]}"
Terraform has compared your real infrastructure against your configuration
and found no differences, so no changes are needed.
exit=0
$ cd /srv/sites && sudo terraform state list
local_file.vhost["docs"]
local_file.vhost["shop"]
random_id.cookie_secret["docs"]
random_id.cookie_secret["shop"]
$ ls /etc/nginx-sites; cmp /tmp/docs.conf /etc/nginx-sites/docs.conf && cmp /tmp/shop.conf /etc/nginx-sites/shop.conf && echo "shop and docs: byte-identical"
docs.conf
shop.conf
shop and docs: byte-identical
```

The blog's file and secret are gone, the state is keyed by name, and `shop.conf` and `docs.conf` are
byte-for-byte what they were before — same ports, same secrets.

**5. Rehearse the next removal.**

```console
$ cd /srv/sites && sudo env CHECKPOINT_DISABLE=1 terraform plan -no-color -var 'sites={docs={port=8102}}' 2>&1 | grep -E '^  # |^Plan:'
  # local_file.vhost["shop"] will be destroyed
  # (because key ["shop"] is not in for_each map)
  # random_id.cookie_secret["shop"] will be destroyed
  # (because key ["shop"] is not in for_each map)
Plan: 0 to add, 0 to change, 2 to destroy.
```

Removing `shop` now plans to touch only `shop`. That is the property the refactoring bought.

**6. Grade.** The blog gone from disk and state, shop and docs unchanged with a clean plan, and every
instance keyed by name — before and after the reboot.

## Common wrong turns

**Applying the `count` plan "because the blog is being removed anyway".** docs gets the blog's port and
secret, and `docs.conf` is deleted by the destroy of `[2]`. Sessions are invalidated and the site moves
port.

**Keeping `count` and putting `"blog"` back as an empty placeholder.** It works until the next removal,
and turns the list into a record of history that everyone must know not to touch.

**Switching to `for_each` without `moved` blocks.** Every instance is destroyed and recreated; every
cookie secret is regenerated. The files may end up identical except for the secrets, which is the part
that mattered.

**Adding moves for `local_file.vhost` only.** The files keep their addresses, and `random_id` instances are
recreated with new values, which the files then pick up on the same apply.

**`toset(var.sites)` with the old list and `8100 + index(...)` for the port.** The port is still derived
from a position, so removing an element still shifts the ports after it. Store the data you mean.

**A move from `[1]` to `["docs"]`.** Index 1 was the blog. The move would carry the blog's secret to docs,
and the plan would then show docs's file being rewritten with it.

**`terraform state rm` for the blog instances.** Terraform forgets them but the blog's file and secret
stay on disk, unmanaged. Let the plan destroy them.

**Skipping `fmt` and `validate`.** They are free and immediate; a typo in `each.value.port` otherwise
surfaces in the middle of reading a plan.

## Cheat sheet

```hcl
resource "x" "y" {
  count = length(var.list)          # instances [0], [1], … — for interchangeable things
  name  = var.list[count.index]
}

resource "x" "y" {
  for_each = var.map                # instances ["key"] — for named things
  name     = each.key
  size     = each.value.size
}

moved {
  from = x.y[0]
  to   = x.y["shop"]
}
```

```console
$ terraform state list                               # [0] = count, ["key"] = for_each
$ terraform fmt -check && terraform validate
$ terraform plan | grep -E '^  # |^Plan:'            # the actions and their reasons
$ terraform plan -var 'sites={docs={port=8102}}'     # rehearse a change without editing files
$ terraform apply
$ terraform plan -detailed-exitcode; echo $?         # 0 = nothing left to do
$ terraform state mv 'x.y[0]' 'x.y["shop"]'          # the one-off alternative to a moved block
$ cmp before after                                   # prove a file did not change
```

## Going deeper

Where this lab's hints send you for reading, beyond this journal. In the TUI, `h` shows a
hint's reading and `l` opens a journal section; the lab's page on the site lists the same.

- *The plan says three to destroy, and you only removed one* (topic journal `terraform`) — Saved plans, and what "stale" protects
- *The plan says three to destroy, and you only removed one* (topic journal `terraform`) — count gives instances numbers, and numbers shift
- *The plan says three to destroy, and you only removed one* (topic journal `terraform`) — for_each gives instances names

The whole subject, end to end: the topic journals *The plan says three to destroy, and you only removed one* (`terraform`), *Resolves here, listens there, routes until Tuesday* (`networking`) —
the mechanism, the symptoms and their causes, exercises, and sources.

## Review

1. With `count = length(["shop", "blog", "docs"])`, what address does the docs site have, and what happens to it when `"blog"` is removed from the list?

   > `[2]`. After the removal docs is described by `[1]` — which is the blog's existing instance, so it is replaced with docs's name but the blog's position-derived port and paired secret — and `[2]` is destroyed as out of range.

2. Why did the docs site inherit the blog's cookie secret in the `count` plan?

   > The secret was chosen by `random_id.cookie_secret[count.index]`; docs moved to index 1, whose `random_id` instance was the blog's, while `cookie_secret[2]` was destroyed.

3. How does `for_each` avoid the shift?

   > Instances are addressed by map keys such as `["docs"]`; removing a key affects only that key's instances, whatever the order or number of the others.

4. Why must the port become explicit data when converting to `for_each`?

   > With `count` it was derived from the index; there is no index in `for_each`, and deriving it from any position would shift it again when an element is removed. Storing `port` per site keeps it fixed.

5. Which `moved` blocks does the conversion need, and why is there none for `[1]`?

   > From `[0]` to `["shop"]` and from `[2]` to `["docs"]`, for both `random_id.cookie_secret` and `local_file.vhost`; `[1]` is the blog, which is meant to be destroyed.

6. What does `(because resource does not use count)` mean in a plan?

   > An instance with an index address remains in state after the resource switched to `for_each`, and no `moved` block claims it, so Terraform will destroy it.

7. How can you check what removing another site would do, without editing any file?

   > Run `terraform plan -var 'sites={…}'` with the map minus that site, and read which addresses the plan destroys.

8. After the apply, how do you prove shop and docs did not change?

   > `terraform plan -detailed-exitcode` exits 0, `terraform state list` shows keyed addresses, and `cmp` against copies taken before shows the files are byte-identical.
