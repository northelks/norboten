#!/bin/sh
# rehearsal.sh [up|check|down] — rehearse the server deploy on a local Ubuntu VM.
#
# A Lima VM plays the VPS: the same Ansible playbook configures it, the same compose project runs
# on it, and the same deploy.sh rolls the API out. Only three things differ from production, and
# they are the three a laptop cannot have: the API image is built here and loaded into the VM
# instead of pulled from GHCR; the domain is norboten.test, resolved on this machine; and Caddy
# issues certificates from its own local CA instead of Let's Encrypt.
#
#   https://norboten.test:8443/        the site     (curl -k, or trust Caddy's root)
#   https://api.norboten.test:8443/    the API
#
# CPUS, MEMORY and DISK size the VM when it is created (4, 6GiB, 40GiB): CPUS=1 MEMORY=2GiB
# DISK=20GiB rehearses the smallest server. An existing VM keeps its size; `down` first.
#
# If the API comes up with `password authentication failed`, the database was created with a
# password the .env no longer holds — a run that stopped half way. The data there is disposable:
#
#   limactl shell norboten-rehearsal sudo sh -c \
#     'cd /opt/norboten && docker compose down && docker volume rm norboten_postgres_data'
set -eu
root=$(cd "$(dirname "$0")/.." && pwd)
limactl=${LIMACTL:-$(ls "${NORBOTEN_HOME:-$HOME/.norboten}"/lima/*/bin/limactl 2>/dev/null | tail -1)}
[ -x "$limactl" ] || { echo "no limactl: run norboten once so it installs its pinned Lima"; exit 1; }
vm=norboten-rehearsal
work=${TMPDIR:-/tmp}/norboten-rehearsal
mkdir -p "$work"

up() {
    if ! "$limactl" list -q | grep -qx "$vm"; then
        cat > "$work/lima.yaml" <<YAML
base: template://ubuntu-lts
cpus: ${CPUS:-4}
memory: ${MEMORY:-6GiB}
disk: ${DISK:-40GiB}
containerd: {system: false, user: false}
portForwards:
  - {guestPort: 443, hostPort: 8443}
  - {guestPort: 80, hostPort: 8081}
YAML
        "$limactl" create --tty=false --name "$vm" "$work/lima.yaml"
    fi
    "$limactl" start "$vm"
    "$limactl" show-ssh --format=config "$vm" > "$work/ssh.config"
    user=$("$limactl" shell "$vm" id -un)
    port=$(awk '/^ *Port /{print $2; exit}' "$work/ssh.config")
    key=$(awk '/^ *IdentityFile /{gsub(/"/,"",$2); print $2; exit}' "$work/ssh.config")

    # Passwords are generated once and then reused, the way install-server.py keeps them in
    # /etc/norboten/install.json. PostgreSQL writes the role's password into its data directory
    # the first time it starts, so handing a second run a fresh one only locks the API out of a
    # database that is already there.
    kept() { "$limactl" shell "$vm" sudo sed -n "s/^$1=//p" /opt/norboten/.env 2>/dev/null; }
    postgres_password=$(kept POSTGRES_PASSWORD); : "${postgres_password:=$(openssl rand -hex 16)}"
    grafana_password=$(kept GRAFANA_ADMIN_PASSWORD); : "${grafana_password:=$(openssl rand -hex 12)}"

    cat > "$work/inventory.yml" <<YAML
all:
  hosts:
    rehearsal:
      ansible_host: 127.0.0.1
      ansible_port: $port
      ansible_user: $user
      ansible_ssh_private_key_file: $key
      ansible_ssh_common_args: "-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"
  vars:
    server_base_admin_user: $user
    norboten_domain: norboten.test
    norboten_caddy_global: local_certs
    norboten_api_image: norboten-api
    norboten_api_tag: rehearsal
    norboten_postgres_password: $postgres_password
    norboten_grafana_admin_password: $grafana_password
YAML

    echo "== the API image, built here and loaded into the VM (a real server pulls it from GHCR)"
    docker build -q -t norboten-api:rehearsal -f "$root/api/Dockerfile" "$root" >/dev/null
    echo "== ansible-playbook playbooks/server.yml — the production playbook, unchanged"
    (cd "$root/ansible" && ANSIBLE_HOST_KEY_CHECKING=False ansible-playbook -i "$work/inventory.yml" \
        playbooks/server.yml -e norboten_skip_deploy=true)
    docker save norboten-api:rehearsal | "$limactl" shell "$vm" sudo docker load

    echo "== the site, as the deploy workflow rsyncs it"
    NORBOTEN_SITE_API=https://api.norboten.test:8443 uv --directory "$root" run python site/build.py >/dev/null
    rsync -az --delete -e "ssh -F $work/ssh.config" "$root/site/dist/" "lima-$vm:/opt/norboten/site/"

    echo "== deploy.sh rehearsal — what the workflow runs over SSH"
    "$limactl" shell "$vm" sudo /opt/norboten/deploy.sh rehearsal
    check
}

check() {
    resolve="--resolve norboten.test:8443:127.0.0.1 --resolve api.norboten.test:8443:127.0.0.1"
    for i in $(seq 1 60); do
        # shellcheck disable=SC2086
        curl -skf $resolve https://api.norboten.test:8443/readyz >/dev/null && break
        sleep 3
    done
    # shellcheck disable=SC2086
    echo "api:  $(curl -sk $resolve https://api.norboten.test:8443/readyz)"
    # shellcheck disable=SC2086
    echo "site: HTTP $(curl -sk -o /dev/null -w '%{http_code}' $resolve https://norboten.test:8443/)"
    "$limactl" shell "$vm" sh -c 'cd /opt/norboten && sudo docker compose ps --format "table {{.Service}}\t{{.Status}}"'
}

down() { "$limactl" delete -f "$vm"; rm -rf "$work"; }

"${1:-up}"
