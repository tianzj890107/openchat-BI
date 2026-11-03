#!/bin/sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
[ -f .env ] || { echo '缺少.env'; exit 1; }
chmod 600 .env
mkdir -p data
chmod 700 data
docker load -i images/cockpit-linux-amd64.tar
docker compose config --quiet
docker compose up -d --pull never
echo '已启动；访问地址见 部署说明.md；docker compose ps 查看健康状态。'
