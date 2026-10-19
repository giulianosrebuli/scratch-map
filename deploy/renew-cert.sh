#!/bin/sh
# Certificado HTTPS do Tailscale para o tlsmux.py (scratch-map-tls) servir HTTPS
# na 5020 (o PWA só instala no Android com HTTPS). Vale para o nome da máquina na
# tailnet (<máquina>.<tailnet>.ts.net) e dura 90 dias: o timer
# scratch-map-cert roda isto todo dia; o tailscale só troca quando falta pouco,
# e o tlsmux (scratch-map-tls) só relê quando o arquivo mudou.
# Precisa: MagicDNS e certificados HTTPS ligados no painel do Tailscale, e o
# usuário como operador (sudo tailscale set --operator=$USER).
set -e
dir="${1:-$HOME/.local/share/scratch-map/tls}"
host=$(tailscale status --json | python3 -c 'import json, sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))')
mkdir -p "$dir"
before=$(cat "$dir/cert.pem" 2>/dev/null | sha256sum)
tailscale cert --cert-file "$dir/cert.pem" --key-file "$dir/key.pem" "$host"
if [ "$before" != "$(sha256sum < "$dir/cert.pem")" ] && systemctl --user -q is-active scratch-map-tls; then
  systemctl --user reload scratch-map-tls
fi
