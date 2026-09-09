#!/usr/bin/env bash
# Show multi-tenant status: flag state, users, namespace assignments.
#
# Usage:
#   ./status.sh
#   OC_DATA_DIR=/opt/opencompany/.opencompany ./status.sh   # EC2 / custom path

source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
check_venv
oc_header "OpenCompany multi-tenant status"
show_data_dir
echo
$MANAGE list
echo
$MANAGE namespace
