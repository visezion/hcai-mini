#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "[setup] Please run with sudo or as root" >&2
  exit 1
fi

UBUNTU_VERSION=$(lsb_release -rs 2>/dev/null || echo "")
if [[ -z "${UBUNTU_VERSION}" ]]; then
  echo "[setup] Unsupported distribution. Ubuntu 22.04/24.04 required." >&2
  exit 1
fi

echo "[setup] Updating apt cache"
apt-get update -y

BASE_PACKAGES=(
  ca-certificates
  curl
  gnupg
  lsb-release
  make
  mosquitto
  mosquitto-clients
  nmap
)

apt-get install -y "${BASE_PACKAGES[@]}"

install_docker_repo() {
  if [[ ! -f /etc/apt/keyrings/docker.gpg ]]; then
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
  fi
  echo \
"deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
$(lsb_release -cs) stable" \
    > /etc/apt/sources.list.d/docker.list
}

if ! command -v docker >/dev/null 2>&1; then
  echo "[setup] Installing Docker Engine"
  install_docker_repo
  apt-get update -y
fi

apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

systemctl enable --now docker

TARGET_USER=${SUDO_USER:-}
if [[ -n "${TARGET_USER}" ]]; then
  if id -nG "${TARGET_USER}" | grep -qw docker; then
    echo "[setup] ${TARGET_USER} already in docker group"
  else
    usermod -aG docker "${TARGET_USER}"
    echo "[setup] Added ${TARGET_USER} to docker group (log out/in to apply)"
  fi
fi

echo "[setup] Dependencies installed. Run 'make up' to start hcai-mini."
