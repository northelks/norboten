---
title: The plan says three to destroy, and you only removed one
topics: [terraform]
minutes: 40
covers: >-
  state as address-to-object map; count versus for_each addressing; moved blocks; prevent_destroy's gap; sensitive values in state; saved plans and staleness; refresh-only drift
---

Terraform's contract is simple to state: you describe what should exist, it compares that with what
its state file says exists, and a plan tells you the difference before anything happens. The whole
safety of the tool rests on that plan being *read* — because the difference Terraform computes is
between addresses in a state file, not between the things you had in mind. Remove one user from a
list and the plan can say three objects will be destroyed. It is not a bug. It is Terraform being
exact about a model you were vague about.

Every example in this journal was run locally with Terraform 1.15.6 and the `hashicorp/random` and
`hashicorp/local` providers, so the passwords and files are stand-ins for anything with an identity —
a database, a bucket, a DNS record — and the plans are real plans. What they show generalises
directly: the dangerous moment is never `apply`, it is the plan you did not read.

## What you should be able to do after this

- Explain what a resource address is, and why Terraform tracks objects by address rather than by
  what they are.
- Predict what `count` does when an item is removed from the middle of a list, and use `for_each` to
  stop it.
- Refactor a configuration — rename a resource, change `count` to `for_each` — without destroying
  anything, using `moved` blocks.
- Say exactly what `lifecycle { prevent_destroy = true }` protects against, and what it does not.
- Know where sensitive values still live in plain text, and treat the state file accordingly.
- Use saved plans, and recognise the error that says a plan no longer matches reality.

## The mechanism

### State maps addresses to real objects

After an apply, Terraform records every object it manages in its state, keyed by **address**:

```console
$ terraform state list
local_file.credentials["alice"]
local_file.credentials["carol"]
random_password.db["alice"]
random_password.db["carol"]
```

`random_password.db["alice"]` is resource type, resource name, and an instance key. Every plan is a
three-way comparison — configuration, state, and (after a refresh) the real object — and every
decision is made per address. If an address is in the configuration and not in state, Terraform
creates it. If it is in state and no longer in the configuration, Terraform destroys it. It has no
notion that "this address used to mean Carol": the address *is* the identity.

That one rule explains nearly every surprising plan.

### `count` gives instances numbers, and numbers shift

```hcl
variable "users" {
  type    = list(string)
  default = ["alice", "bob", "carol"]
}

resource "random_password" "db" {
  count   = length(var.users)
  length  = 20
  special = false
}

resource "local_file" "credentials" {
  count           = length(var.users)
  filename        = "${path.module}/out/${var.users[count.index]}.env"
  content         = "DB_USER=${var.users[count.index]}\nDB_PASSWORD=${random_password.db[count.index].result}\n"
  file_permission = "0600"
}
```

With `count`, the instances are `random_password.db[0]`, `[1]`, `[2]` — and the only thing tying index
`2` to Carol is her position in a list. Remove Bob and Carol moves from position 2 to position 1:

```console
$ terraform plan -var 'users=["alice","carol"]'
  # local_file.credentials[1] must be replaced
      ~ content              = (sensitive value) # forces replacement
      ~ filename             = "./out/bob.env" -> "./out/carol.env" # forces replacement
  # local_file.credentials[2] will be destroyed
  # (because index [2] is out of range for count)
  # random_password.db[2] will be destroyed
  # (because index [2] is out of range for count)
Plan: 1 to add, 0 to change, 3 to destroy.
```

Read it address by address. Index `[1]` — which was Bob — survives as a password and is re-pointed at
Carol's file. Index `[2]` — which was Carol — is destroyed, *including her password*. Applied, the
effect on the lab directory was precise:

```
carol before: GLMGbE…   bob before: KWOR0s…   carol after: KWOR0s…
```

Carol now has Bob's old password, and her own is gone. Substitute a database, a volume or a DNS record
for the password and "we removed a user" becomes "we destroyed someone else's data and handed their
successor the wrong credentials". The plan said so, in plain English, before anything happened.

### `for_each` gives instances names

```hcl
resource "random_password" "db" {
  for_each = toset(var.users)
  length   = 20
  special  = false
}

resource "local_file" "credentials" {
  for_each        = toset(var.users)
  filename        = "${path.module}/out/${each.key}.env"
  content         = "DB_USER=${each.key}\nDB_PASSWORD=${random_password.db[each.key].result}\n"
  file_permission = "0600"
}
```

Now the addresses are `random_password.db["alice"]`, `["bob"]`, `["carol"]`, and removing Bob touches
only Bob:

```console
$ terraform plan -var 'users=["alice","carol"]'
  # local_file.credentials["bob"] will be destroyed
  # (because key ["bob"] is not in for_each map)
  # random_password.db["bob"] will be destroyed
  # (because key ["bob"] is not in for_each map)
Plan: 0 to add, 0 to change, 2 to destroy.
```

The rule of thumb: `count` for *how many* identical things (`count = var.enabled ? 1 : 0` is its best
use), `for_each` for *which* things, whenever each one has an identity of its own.

### Refactoring without destroying: `moved`

Changing `count` to `for_each` changes every address, and without further instruction Terraform does
exactly what the address rule says — destroy the old ones, create the new ones:

```console
$ terraform plan
Plan: 6 to add, 0 to change, 6 to destroy.
```

A `moved` block tells Terraform that an address has been renamed, so the object in state is carried
over rather than replaced:

```hcl
moved {
  from = random_password.db[0]
  to   = random_password.db["alice"]
}
moved {
  from = random_password.db[1]
  to   = random_password.db["bob"]
}
# … one per instance, for each resource
```

```console
$ terraform plan
  # random_password.db[0] has moved to random_password.db["alice"]
  # random_password.db[1] has moved to random_password.db["bob"]
  …
Plan: 0 to add, 0 to change, 0 to destroy.
```

The same block handles renaming a resource (`from = aws_instance.web`, `to = aws_instance.frontend`)
and moving it into a module. It is reviewed in a pull request like any other code, which is its
advantage over the older `terraform state mv`: the refactoring and its safety net land together.
Keep `moved` blocks until every copy of the state has been applied with them, then they can go.

### `prevent_destroy`, and the hole in it

```hcl
resource "random_password" "db" {
  for_each = toset(var.users)
  length   = 20
  special  = false

  lifecycle {
    prevent_destroy = true
  }
}
```

Any plan that would destroy one of these instances now fails before anything is applied:

```
Error: Instance cannot be destroyed

  on main.tf line 13:
  13: resource "random_password" "db" {

Resource random_password.db["erin"] has lifecycle.prevent_destroy set, but
the plan calls for this resource to be destroyed. To avoid this error and
continue with the plan, either disable lifecycle.prevent_destroy or reduce
the scope of the plan using the -target option.
```

It also refuses `terraform plan -destroy`. What it cannot do is protect a resource whose **block has
been deleted**: the `lifecycle` setting lives inside the block, so deleting the block deletes the
protection with it. Verified with a small resource: applied with `prevent_destroy = true`, block
removed, and the next plan read

```
  # random_pet.keep will be destroyed
  # (because random_pet.keep is not in configuration)
Plan: 0 to add, 0 to change, 1 to destroy.
```

with no error at all. `prevent_destroy` guards against a plan that replaces or removes something by
accident while the resource is still written down. For the objects you cannot afford to lose, the
real protection lives in the provider — deletion protection on a database, versioning on a bucket —
where deleting a line of HCL cannot switch it off.

### Sensitive is a display setting

```hcl
output "first_password" {
  value     = random_password.db["alice"].result
  sensitive = true
}
```

`sensitive = true` hides a value in plans, apply output and the bulk `terraform output` listing:

```console
$ terraform output
first_password = <sensitive>
```

It does not encrypt anything, and it does not hide the value from someone who asks for it by name:

```console
$ terraform output first_password
"7xK9s5oXE32bAfyfgvWc"
```

And the state file holds every attribute of every resource in plain text — the generated passwords
included. On the lab machine the password appeared in `terraform.tfstate` and again in
`terraform.tfstate.backup`, and both files had been written `0644`. State is a secret. It does not go in
git; a shared state lives in a backend with encryption at rest, access control and locking (so two
applies cannot write it at once); and the people who can read state can read everything in it.

### Saved plans, and what "stale" protects

`terraform plan -out=FILE` saves the exact plan; `terraform apply FILE` applies that plan and nothing
else, without re-planning — which is what makes a reviewed plan meaningful. If the state changes after
the plan was saved, the saved plan is refused:

```console
$ terraform plan -out=add-dave.plan -var 'users=["alice","carol","dave"]'
Plan: 2 to add, 0 to change, 0 to destroy.
$ terraform apply -auto-approve -var 'users=["alice","carol","erin"]'      # someone else applies
Apply complete! Resources: 2 added, 0 changed, 0 destroyed.
$ terraform apply add-dave.plan
Error: Saved plan is stale
The given plan file can no longer be applied because the state was changed by
another operation after the plan was created.
```

That error is a feature: the plan you reviewed described a world that no longer exists. Plan again.

### Drift

Change a managed object outside Terraform and the next plan's refresh notices. What it does about it
depends on the provider. For `local_file`, a file whose content no longer matches is treated as gone:

```console
$ echo "DB_PASSWORD=edited-by-hand" > out/carol.env
$ terraform plan -var 'users=["alice","carol"]'
  # local_file.credentials["carol"] will be created
Plan: 1 to add, 0 to change, 0 to destroy.
```

Cloud providers more often show an in-place update, or a replacement if the drifted attribute cannot be
changed in place. Either way the plan is the only place drift is reported, which is one more reason to
plan regularly even when nobody has changed the code: `terraform plan -detailed-exitcode` exits `2`
when there are changes, which makes a drift check a one-line scheduled job.

## A failure, walked through

A configuration creates database credentials for a list of users. Bob has left; someone removes him
from the list and runs `terraform apply -auto-approve` in CI. The next morning Carol cannot log in.

**1. Reconstruct the plan the pipeline did not show anyone.** Put the list back as it was and plan the
change again:

```console
$ terraform plan -var 'users=["alice","carol"]'
  # local_file.credentials[1] must be replaced
      ~ filename             = "./out/bob.env" -> "./out/carol.env" # forces replacement
  # local_file.credentials[2] will be destroyed
  # (because index [2] is out of range for count)
  # random_password.db[2] will be destroyed
  # (because index [2] is out of range for count)
Plan: 1 to add, 0 to change, 3 to destroy.
```

*3 to destroy* for removing one person. The address explains it: `count` instances are numbered, and
Carol was number 2.

**2. Confirm what actually happened to Carol.**

```
carol before: GLMGbE…   bob before: KWOR0s…   carol after: KWOR0s…
```

Her credential file now carries Bob's old password, and her own password object was destroyed. That is
the incident: not an outage in Terraform, but an exact execution of an ambiguous design.

**3. Stop it happening again: move to `for_each`, without destroying anything.** Change both resources
to `for_each = toset(var.users)` and plan first:

```console
$ terraform plan
Plan: 6 to add, 0 to change, 6 to destroy.
```

Every address changed, so everything would be rebuilt — every user's password regenerated. Add a
`moved` block per instance, mapping `[0]` → `["alice"]`, `[1]` → `["bob"]`, `[2]` → `["carol"]` for both
resources, and plan again:

```console
$ terraform plan
  # local_file.credentials[0] has moved to local_file.credentials["alice"]
  …
  # random_password.db[2] has moved to random_password.db["carol"]
Plan: 0 to add, 0 to change, 0 to destroy.
$ terraform apply -auto-approve
Apply complete! Resources: 0 added, 0 changed, 0 destroyed.
```

(The mapping has to reflect the list *at the time*; here Bob had been re-added before the migration so
that indices matched names. Get it wrong and the moved blocks faithfully swap two people.)

**4. Remove Bob again, and read the plan.**

```console
$ terraform plan -var 'users=["alice","carol"]'
  # local_file.credentials["bob"] will be destroyed
  # (because key ["bob"] is not in for_each map)
  # random_password.db["bob"] will be destroyed
  # (because key ["bob"] is not in for_each map)
Plan: 0 to add, 0 to change, 2 to destroy.
```

Two objects, both Bob's. Applied, Alice and Carol keep their passwords.

**5. Make the pipeline show the plan it applies.** The failure was never `count`; it was an apply
nobody reviewed. Save the plan, have a human or a policy check read it, and apply that file:

```console
$ terraform plan -out=change.plan -var 'users=["alice","carol"]'
$ terraform show change.plan          # the review
$ terraform apply change.plan         # exactly what was reviewed — or "Saved plan is stale"
```

**6. Add a guard where a mistake is expensive** — `prevent_destroy` on the password resources turns
any plan that would destroy one into an error, and the stale-plan check stops a reviewed plan being
applied to a changed world. Neither replaces reading the plan; both make not reading it fail loudly.

## Common wrong turns

**`apply -auto-approve` without a saved, reviewed plan.** The plan is the only moment Terraform tells
you what it is about to destroy. In CI, `plan -out`, review, `apply FILE`.

**`count` over a list of named things.** Removing or reordering an item re-keys every instance after
it. Use `for_each` over a set or map whenever the things have identities.

**Changing `count` to `for_each` (or renaming a resource) and applying.** Every address changes, so
everything is destroyed and recreated. Add `moved` blocks and plan until it says `0 to destroy`.

**Writing `moved` blocks from memory.** They map old addresses to new ones exactly as you say. Check
`terraform state list` and the current list order before writing them.

**Relying on `prevent_destroy` to protect a resource someone might delete from the code.** The setting
is deleted with the block. Use provider-side deletion protection for things that must survive a bad
commit.

**Treating `sensitive = true` as encryption.** It hides values from plan output and from the bulk
`terraform output` listing. `terraform output NAME` prints it, and the state file stores it in plain
text.

**Committing `terraform.tfstate`.** It contains every secret the configuration touches — and so does
`terraform.tfstate.backup`. Remote backend, encrypted, access-controlled, locked.

**Re-running `apply` on a stale saved plan by re-planning silently.** The error means the world changed
since the review. Plan again and review again.

**Using `-target` to get past an error.** It applies part of a configuration and leaves state
inconsistent with the rest; HashiCorp recommends it only for exceptional recovery. The error it is
tempting to bypass — like `Instance cannot be destroyed` — is usually the plan working.

**Assuming drift shows up without a plan.** Nothing notices a hand edit until the next refresh. Run a
scheduled `plan -detailed-exitcode` if drift matters.

## Symptoms and causes

| Symptom | Usual cause | The evidence |
|---|---|---|
| a rename in the code plans a destroy and a create | the address changed and state still has the old one | `terraform state list`; a `moved` block |
| removing one item from a list replaces the items after it | `count` addresses instances by position | the plan's `[1] -> [0]` changes; switch to `for_each` |
| a plan shows changes nobody made in the code | drift: the real object was changed outside Terraform | `terraform plan -refresh-only` |
| a secret appears in plain text on disk | state stores every attribute, `sensitive` values included | `terraform.tfstate` and its backup's permissions; a remote backend |
| applying a saved plan fails as stale | state changed since the plan was made | `terraform show PLANFILE`; plan again |
| `prevent_destroy` did not stop a deletion | the resource block itself was removed, taking the lifecycle rule with it | the diff of the configuration |

## Cheat sheet

```console
# read before you change
terraform plan                               # the diff between config, state and reality
terraform plan -out=change.plan              # save it…
terraform show change.plan                   # …review it…
terraform apply change.plan                  # …apply exactly that ("Saved plan is stale" if state moved)
terraform plan -destroy                      # what destroy would touch
terraform plan -detailed-exitcode            # exit 0 no changes, 1 error, 2 changes — for drift checks

# state is identity
terraform state list                         # every managed address
terraform state show 'random_password.db["alice"]'
# address = TYPE.NAME[index] (count) or TYPE.NAME["key"] (for_each)

# refactoring safely
# moved { from = random_password.db[0]  to = random_password.db["alice"] }
# plan until: Plan: 0 to add, 0 to change, 0 to destroy.

# count vs for_each
# count    = var.enabled ? 1 : 0            ← how many
# for_each = toset(var.users)               ← which ones (each.key / each.value)

# guards
# lifecycle { prevent_destroy = true }       ← fails any plan that destroys it; gone if the block is deleted
# lifecycle { create_before_destroy = true } ← replacement creates the new one first
# lifecycle { ignore_changes = [tags] }      ← tolerate drift in named attributes

# secrets
terraform output                             # sensitive values shown as <sensitive>
terraform output NAME                        # …but printed in full when asked by name
# terraform.tfstate and .backup: plain text, every attribute — never in git
```

## Exercises

1. Create two resources with `count`, remove the first from the list, and read the plan; convert to
   `for_each` with `moved` blocks so that the conversion plans no change.
2. Rename a resource and plan; add a `moved` block and plan again.
3. Change a managed file by hand and compare `terraform plan` with `terraform plan -refresh-only`.
4. Mark an output `sensitive`, apply, and search the state file for the value.
5. Save a plan, change state with another apply, and try to apply the saved plan.

## Sources

- State: https://developer.hashicorp.com/terraform/language/state
- `for_each`: https://developer.hashicorp.com/terraform/language/meta-arguments/for_each
- Refactoring with `moved`: https://developer.hashicorp.com/terraform/language/modules/develop/refactoring
- `terraform plan -help`, `terraform state -help` — the flags, on the machine itself.

## Review

1. A list of three users feeds `count`. Removing the middle user produces `Plan: 1 to add, 0 to change,
   3 to destroy`. Explain every line of that plan.

   > `count` instances are identified by index. Removing the middle item moves the last user from index
   > 2 to index 1: index 1's file must be replaced to point at the new name, and index 2 — the last user's
   > password and file — is out of range and destroyed. The surviving index-1 password, which belonged to
   > the removed user, is reused for the last user.

2. Why does `for_each` over a set of names avoid that problem?

   > Instances are keyed by the name itself (`["carol"]`), so removing one key destroys only that key's
   > objects; the other addresses do not change.

3. You change a resource from `count` to `for_each` and the plan says `6 to add, 6 to destroy`. What
   do you add, and what should the plan say afterwards?

   > One `moved` block per instance mapping each old indexed address to its new key, e.g. `from =
   > random_password.db[0]`, `to = random_password.db["alice"]`. The plan should then report the moves
   > and `0 to add, 0 to change, 0 to destroy`.

4. A resource has `lifecycle { prevent_destroy = true }`. Name one situation where it is destroyed
   anyway, without any error.

   > When its resource block is deleted from the configuration: the lifecycle setting is deleted with it,
   > and Terraform plans the destroy because the address is no longer in configuration. Protection that
   > must survive a bad commit belongs in the provider (deletion protection, versioning).

5. An output is marked `sensitive = true`. Where can its value still be read in plain text?

   > In `terraform output NAME` (asking by name prints it), and in the state file and its backup, which
   > store every attribute unencrypted. `sensitive` only suppresses display in plans, applies and the
   > bulk output listing.

6. `terraform apply change.plan` fails with *Saved plan is stale*. What happened, and what do you do?

   > The state changed after the plan was saved — another apply ran — so the reviewed plan describes a
   > world that no longer exists. Run `plan -out` again and review the new plan; do not bypass it.

7. Someone edits a managed file by hand. When does Terraform notice, and how does the `local_file`
   provider represent the change?

   > Only on the next refresh, which every plan performs. `local_file` treats a file whose content no
   > longer matches as absent and plans to create it; other providers may show an update or a
   > replacement. A scheduled `plan -detailed-exitcode` turns drift into an alert.

8. Why is `terraform.tfstate` a secret even when every sensitive output is marked sensitive?

   > State stores every attribute of every managed object in plain text — generated passwords, keys,
   > connection strings — regardless of `sensitive`. Anyone who can read the state can read all of them,
   > which is why it lives in an encrypted, access-controlled backend and never in version control.
