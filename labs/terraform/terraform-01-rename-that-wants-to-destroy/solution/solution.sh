#!/bin/sh
set -eu
cd /srv/infra
export CHECKPOINT_DISABLE=1 TF_IN_AUTOMATION=1 TF_INPUT=0
cat > moved.tf <<'HCL'
# the resources were renamed; these keep the existing objects instead of replacing them
moved {
  from = random_password.key
  to   = random_password.session_key
}

moved {
  from = local_file.env
  to   = local_file.app_env
}
HCL
terraform apply -auto-approve
chmod 600 terraform.tfstate*
