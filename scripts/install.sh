#!/usr/bin/env sh
# Bootstrap a GHCR-based deployment without cloning the application source.
set -eu

REPOSITORY="${TG_DL_BOT_REPOSITORY:-phoenix-yyj/TG-DL-BOT}"
REF="${TG_DL_BOT_REF:-main}"
INSTALL_DIR="${1:-./tg-dl-bot}"
BASE_URL="https://raw.githubusercontent.com/${REPOSITORY}/${REF}"

if command -v curl >/dev/null 2>&1; then
  download() {
    curl --fail --location --silent --show-error "$1" --output "$2"
  }
elif command -v wget >/dev/null 2>&1; then
  download() {
    wget --quiet "$1" --output-document="$2"
  }
else
  echo "错误：请先安装 curl 或 wget。" >&2
  exit 1
fi

mkdir -p "$INSTALL_DIR"
cd "$INSTALL_DIR"

tmp_suffix=".$$"
cleanup() {
  rm -f "docker-compose.yml${tmp_suffix}" ".env.example${tmp_suffix}"
}
trap cleanup 0
trap 'exit 1' HUP INT TERM

echo "下载 Docker Compose 配置..."
download "${BASE_URL}/docker-compose.yml" "docker-compose.yml${tmp_suffix}"
mv "docker-compose.yml${tmp_suffix}" docker-compose.yml

echo "下载环境变量模板..."
download "${BASE_URL}/.env.example" ".env.example${tmp_suffix}"
mv ".env.example${tmp_suffix}" .env.example

if [ ! -e .env ]; then
  cp .env.example .env
  echo "已从 .env.example 创建 .env。"
else
  echo "保留已有 .env，未覆盖现有配置。"
fi

mkdir -p downloads sessions attached_assets

echo "项目文件已准备完成：$(pwd)"
echo "请先编辑 .env 填写 API_ID、API_HASH、BOT_TOKEN 和 OWNER_USER_ID，然后执行："
echo "  cd '$INSTALL_DIR'"
echo "  docker compose pull && docker compose up -d"
