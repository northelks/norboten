---
title: Terraform knows your resources by their address
topics: [terraform, users-permissions]
minutes: 40
---

A pull request renamed two resources in `/srv/infra` — `random_password.key` became
`random_password.session_key`, `local_file.env` became `local_file.app_env` — because the new names
say what the things are. Nothing about the objects changed. The next `terraform plan` proposed to
destroy the session key and create a new one, which would log out every customer, and to destroy and
recreate the file that holds it.

Terraform was not being obtuse. It identifies every object it manages by its **address** in the
configuration, and it records that address, with the object's attributes, in state. A rename in the
code is, to Terraform, one address disappearing and another appearing: the object at the old address
is no longer wanted, and nothing exists yet at the new one. The information "these are the same thing"
is not in the configuration unless you put it there — with a `moved` block.

The same plan also wanted to put back a file someone had edited by hand during an incident, and the
state file that held the session key in plain text was readable by every account. This journal is
about the relationship between configuration, state and reality, and how to change the first without
destroying the third.

## What you should be able to do after this

- Explain what Terraform state records and why an address change looks like destroy-and-create.
- Refactor resource names with `moved` blocks (or `terraform state mv`), and verify with a plan before
  applying.
- Read a plan's reasons: "not in configuration", "will be created", "has moved to", "must be replaced".
- Recognise drift, and decide whether to let Terraform correct it or to change the configuration.
- Say which secrets end up in state, and protect state files and their backups accordingly.
- Use `terraform plan -detailed-exitcode` as a machine-readable "anything to do?" check.

## The mechanism

### Configuration, state, reality

Terraform works with three things:

- **Configuration** — the `.tf` files: what you want, by address (`random_password.session_key`).
- **State** — `terraform.tfstate`: for each address, the object Terraform created and its last known
  attributes, including provider-generated values such as a random password's `result`.
- **Reality** — the actual objects: here, files on disk and values that exist only in state.

`terraform plan` refreshes state from reality (asking each provider to read its objects), then compares
the refreshed state with the configuration and proposes actions to make reality match the
configuration. `terraform state list` shows the addresses in state; `grep resource *.tf` shows the
addresses in configuration. When they differ, the plan tells you why.

### Why a rename becomes destroy-and-create

After the rename, state contains `random_password.key` and configuration contains
`random_password.session_key`. The plan says exactly that:

- `random_password.key will be destroyed (because random_password.key is not in configuration)`
- `random_password.session_key will be created`

For most resources that is expensive; for a `random_password` it is destructive in a subtle way: the new
object gets a new random value. Anything derived from it — the session key in `/etc/shop/app.env` —
changes on apply. The provider did exactly what the configuration asked.

### `moved` blocks

```hcl
moved {
  from = random_password.key
  to   = random_password.session_key
}
```

A `moved` block records that the object at one address now lives at another. During plan, Terraform
updates the address in state before comparing, so the plan shows `random_password.key has moved to
random_password.session_key` and no destroy. Moves apply to modules, `count`/`for_each` instances and
whole resources alike.

Two properties make `moved` better than the older command `terraform state mv`:

- It is **code**: reviewed in the same pull request as the rename, and applied by every workspace and
  every colleague's state automatically, instead of a manual state edit someone has to remember.
- It shows up in the **plan**, so the move is visible before anything happens.

Keep moved blocks until every state that could contain the old address has been applied — for a shared
module, that can be a long time. A moved block whose `from` no longer exists anywhere is harmless.

`terraform state mv OLD NEW` still has its place for one-off surgery on a single state, and it writes a
backup first.

### Drift

Someone appended two lines to `/etc/shop/nginx-site.conf`, a file Terraform manages with `local_file`.
When the `local` provider reads that resource during refresh and finds the file's content no longer
matches what it wrote, it reports the object as gone; the plan then shows `local_file.nginx_site will be
created`. Other providers show drift as `~ update in-place` or `must be replaced`. In all cases the
decision is the same and it is a human one:

- If the manual change was a temporary hack, **let Terraform put reality back** (apply).
- If the change is wanted, **put it in the configuration** first, so the plan becomes empty without
  undoing it.

`terraform plan -refresh-only` shows only the drift, without the configuration's proposals, which helps
when the two are mixed.

### Secrets in state

State stores every attribute a provider returns. A `random_password`'s `result` is marked sensitive,
which only means Terraform prints `(sensitive value)` in plans. In `terraform.tfstate` it is plain
text, and so is the content of `local_file.app_env`. Whoever can read the state can read the secrets.

For a local state file:

- mode 0600, owned by the account that runs Terraform;
- `terraform.tfstate.backup` too — Terraform writes the previous state there on every apply, with the
  same secrets;
- never in Git (`*.tfstate*` in `.gitignore`).

For a team, a remote backend with encryption and access control, and state locking, replaces the local
file. Newer Terraform versions add ephemeral values and write-only arguments that keep some secrets out
of state altogether; for generated secrets like this one, protecting state is the baseline.

### `-detailed-exitcode`

`terraform plan -detailed-exitcode` exits `0` when there is nothing to do, `2` when there are changes,
and `1` on error. It turns "is this infrastructure exactly as configured?" into a status a script or a
check can test — which is how the lab grades a clean plan. Add `-lock=false` only for read-only checks
that must not wait on a lock.

## A failure, walked through

Replayed on the track's lab VM before its image moved to Ubuntu 26.04; the output below is what
the machine printed. Terraform's
providers come from the image's local mirror; `CHECKPOINT_DISABLE=1` stops the version check.

**1. Read the plan everyone was afraid of** (filtered to the lines that carry the decisions):

```console
$ cd /srv/infra && sudo env CHECKPOINT_DISABLE=1 terraform plan -no-color 2>&1 | grep -E '^  # |^Plan:|must be replaced|will be (created|destroyed)|forces replacement|^\s+[-+~]'
  + create
  - destroy
  # local_file.app_env will be created
  + resource "local_file" "app_env" {
      + content              = (sensitive value)
…
      + filename             = "/etc/shop/app.env"
      + id                   = (known after apply)
  # local_file.env will be destroyed
  # (because local_file.env is not in configuration)
  - resource "local_file" "env" {
      - content              = (sensitive value) -> null
…
      - filename             = "/etc/shop/app.env" -> null
      - id                   = "0d5937fb5cad3bcab0017ff8a6b92cc67197313d" -> null
  # local_file.nginx_site will be created
  + resource "local_file" "nginx_site" {
      + content              = <<-EOT
…
  # random_password.key will be destroyed
  # (because random_password.key is not in configuration)
  - resource "random_password" "key" {
…
      - result      = (sensitive value) -> null
…
  # random_password.session_key will be created
  + resource "random_password" "session_key" {
…
      + result      = (sensitive value)
…
Plan: 3 to add, 0 to change, 2 to destroy.
```

(Lines marked `…` are the remaining attributes of each resource, omitted here.) Two destroys "because
… is not in configuration", three creates. `nginx_site` is being *created* although it exists — the
drift.

**2. Compare state with configuration, and look at the drifted file.**

```console
$ cd /srv/infra && sudo terraform state list
local_file.env
local_file.nginx_site
random_password.key
$ grep -n '^resource' /srv/infra/main.tf
6:resource "random_password" "session_key" {
11:resource "local_file" "app_env" {
17:resource "local_file" "nginx_site" {
$ tail -n 3 /etc/shop/nginx-site.conf
}
# incident 2026-09-11: let the office in directly
allow 203.0.113.0/24;
```

State has the old names; configuration has the new ones. The site file carries an incident-era edit
that the configuration never had.

**3. See what the state holds, and who can read it.**

```console
$ ls -l /srv/infra/terraform.tfstate*
-rw-r--r-- 1 root root 4634 Sep 14 04:02 /srv/infra/terraform.tfstate
$ sudo jq -r '.resources[] | select(.type=="random_password") | .instances[0].attributes.result' /srv/infra/terraform.tfstate | cut -c1-6 | sed 's/$/… (first 6 characters)/'
3dBlUW… (first 6 characters)
$ sudo sed -n 's/^SESSION_KEY=\(.\{6\}\).*/SESSION_KEY=\1…/p' /etc/shop/app.env
SESSION_KEY=3dBlUW…
```

The session key is in the state in plain text (only its first characters are shown here), matching the
live file — and the state is world-readable.

**4. Declare the renames.** `/srv/infra/moved.tf`:

```hcl
# the resources were renamed; these keep the existing objects instead of replacing them
moved {
  from = random_password.key
  to   = random_password.session_key
}

moved {
  from = local_file.env
  to   = local_file.app_env
}
```

```console
$ cd /srv/infra && sudo env CHECKPOINT_DISABLE=1 terraform plan -no-color 2>&1 | grep -E '^  # |^Plan:|has moved to|must be replaced'
  # local_file.env has moved to local_file.app_env
  # local_file.nginx_site will be created
  # random_password.key has moved to random_password.session_key
Plan: 1 to add, 0 to change, 0 to destroy.
```

No destroys left. The only action is putting back the hand-edited file — which is wanted here: the
incident exception was temporary.

**5. Apply, then plan again.**

```console
$ cd /srv/infra && sudo env CHECKPOINT_DISABLE=1 terraform apply -auto-approve -no-color 2>&1 | grep -E 'Moving|Destroying|Destruction complete|Creating|Creation complete|^Apply complete'
local_file.nginx_site: Creating...
local_file.nginx_site: Creation complete after 0s [id=318de722cf0f0b8137a229f55664760dd1018e07]
Apply complete! Resources: 1 added, 0 changed, 0 destroyed.
$ cd /srv/infra && sudo env CHECKPOINT_DISABLE=1 terraform plan -detailed-exitcode -no-color 2>&1 | tail -n 3; echo "exit=${PIPESTATUS[0]}"

Terraform has compared your real infrastructure against your configuration
and found no differences, so no changes are needed.
exit=0
$ cd /srv/infra && sudo terraform state list
local_file.app_env
local_file.nginx_site
random_password.session_key
$ sudo jq -r '.resources[] | select(.type=="random_password") | .instances[0].attributes.result' /srv/infra/terraform.tfstate | cut -c1-6 | sed 's/$/… (first 6 characters)/'; sudo sed -n 's/^SESSION_KEY=\(.\{6\}\).*/SESSION_KEY=\1…/p' /etc/shop/app.env
3dBlUW… (first 6 characters)
SESSION_KEY=3dBlUW…
$ tail -n 3 /etc/shop/nginx-site.conf
    server_name shop.example.test;
    root /srv/www/current;
}
```

The moves happened as part of the apply without any destroy, the state now uses the new addresses, the
session key is unchanged, the site file is back to its configured content, and the plan exits 0.

**6. Protect the state and its backup.**

```console
$ ls -l /srv/infra/terraform.tfstate*
-rw-r--r-- 1 root root 4654 Sep 14 04:02 /srv/infra/terraform.tfstate
-rw-r--r-- 1 root root 4634 Sep 14 04:02 /srv/infra/terraform.tfstate.backup
$ sudo chmod 600 /srv/infra/terraform.tfstate /srv/infra/terraform.tfstate.backup && ls -l /srv/infra/terraform.tfstate*
-rw------- 1 root root 4654 Sep 14 04:02 /srv/infra/terraform.tfstate
-rw------- 1 root root 4634 Sep 14 04:02 /srv/infra/terraform.tfstate.backup
$ cd /srv/infra && sudo env CHECKPOINT_DISABLE=1 terraform plan -no-color 2>&1 | tail -n 2 && ls -l /srv/infra/terraform.tfstate*
Terraform has compared your real infrastructure against your configuration
and found no differences, so no changes are needed.
-rw------- 1 root root 4654 Sep 14 04:02 /srv/infra/terraform.tfstate
-rw------- 1 root root 4634 Sep 14 04:02 /srv/infra/terraform.tfstate.backup
```

The apply created a `.backup` — with the previous state and the same secret — world-readable like the
state itself. Both are 0600 now. A plan that changes nothing does not rewrite them; check the modes
again after future applies, or keep the state somewhere whose permissions do not depend on each write.

**7. Grade.** A clean plan, the original key under its new address and in the file, and root-only
state — before and after the reboot.

## Common wrong turns

**Renaming the resources back.** The plan becomes empty and the team's agreed names are lost; the next
rename hits the same wall. `moved` is how refactoring is supposed to work.

**`terraform apply` after a quick look at "3 to add".** The two destroys are in the same plan. Read the
`Plan:` line in full, and every `will be destroyed`.

**`terraform import random_password.session_key …`.** Import brings an existing real object under an
address; the object here already *is* under management, at another address. Import would leave the old
address to be destroyed, and not every resource type supports import at all.

**`terraform state rm random_password.key` followed by apply.** Terraform forgets the old key and
creates a new one for the new address — exactly the regeneration you were avoiding.

**`lifecycle { prevent_destroy = true }` on the new address.** It protects the new address, which has
nothing to destroy; the plan to destroy the old address still stands.

**Editing `terraform.tfstate` by hand.** It usually works once and corrupts serial numbers or lineage the
next time. Use `moved` or `terraform state mv`, which write backups.

**Silencing the drift with `lifecycle { ignore_changes = [content] }`.** The incident edit then stays
forever, unreviewed, in a file the configuration claims to manage.

**Protecting `terraform.tfstate` and forgetting `.backup`.** The backup holds the previous state, with the
same secrets.

## Cheat sheet

```console
$ terraform plan                                   # refresh, compare, propose
$ terraform plan -detailed-exitcode                # 0 nothing to do, 2 changes, 1 error
$ terraform plan -refresh-only                     # only the drift between state and reality
$ terraform state list                             # addresses in state
$ terraform state show random_password.session_key # one object's recorded attributes
$ terraform state mv OLD NEW                       # one-off move in one state (writes a backup)
$ terraform apply -auto-approve                    # in automation, apply a reviewed plan instead
$ jq '.resources[].type' terraform.tfstate         # what the state holds (it is JSON)
$ chmod 600 terraform.tfstate terraform.tfstate.backup
```

```hcl
moved {
  from = random_password.key          # old address
  to   = random_password.session_key  # new address
}
```

| Plan says | Meaning |
|---|---|
| `will be destroyed (because … is not in configuration)` | an address exists only in state |
| `will be created` | an address exists only in configuration — or the object vanished or drifted (provider-specific) |
| `has moved to` | a `moved` block matched; no destroy |
| `must be replaced` / `forces replacement` | an argument that cannot change in place differs |
| `~ update in-place` | an attribute differs and can be changed |

## Going deeper

Where this lab's hints send you for reading, beyond this journal. In the TUI, `h` shows a
hint's reading and `l` opens a journal section; the lab's page on the site lists the same.

- *The plan says three to destroy, and you only removed one* (topic journal `terraform`) — State maps addresses to real objects
- *The plan says three to destroy, and you only removed one* (topic journal `terraform`) — Drift
- *The plan says three to destroy, and you only removed one* (topic journal `terraform`) — Refactoring without destroying: moved
- *The plan says three to destroy, and you only removed one* (topic journal `terraform`) — Sensitive is a display setting

The whole subject, end to end: the topic journal *The plan says three to destroy, and you only removed one* (`terraform`) —
the mechanism, the symptoms and their causes, exercises, and sources.

## Review

1. Why does renaming a resource in the configuration produce a destroy and a create?

   > Terraform identifies objects by address; after the rename, state has an object at the old address that is no longer in configuration (destroy) and configuration has a new address with no object (create).

2. What does a `moved` block do during plan, and why is it preferable to `terraform state mv`?

   > It rewrites the address in state before comparison, so the plan shows a move instead of destroy and create; it lives in version control, is reviewed with the rename, and applies to every state that runs the configuration.

3. Why would destroying and recreating `random_password.key` log out customers, even though the configuration of the new resource is identical?

   > A new `random_password` generates a new random value, and the session key file is derived from it.

4. The plan says `local_file.nginx_site will be created` although the file exists. What happened?

   > The file was edited by hand; the local provider saw its content no longer matched what it wrote and reported the object as gone, so Terraform plans to write it again.

5. Which files contain the session key in plain text, and what mode should they have?

   > `/etc/shop/app.env`, `terraform.tfstate` and `terraform.tfstate.backup`; the state files should be 0600 and owned by the account that runs Terraform (and never committed).

6. What does `terraform plan -detailed-exitcode` return, and why is it useful in a check?

   > 0 when there are no changes, 2 when there are changes, 1 on error — a status a script can test to prove the infrastructure matches its configuration.

7. Why is `terraform state rm random_password.key` not a fix?

   > It makes Terraform forget the existing object; the new address still has no object, so the next apply creates a new random password anyway.

8. When should drift be applied away, and when should the configuration change instead?

   > Apply it away when the manual change was unwanted or temporary; change the configuration first when the manual change is correct and must be kept.
