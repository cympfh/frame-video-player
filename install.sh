#!/bin/bash
# frame-video-player を Steam Frame(SteamOS)に入れる。ユーザー領域だけを使う(sudo は使わない)。
#   ./install.sh              入れる / 新しくする(SteamVR が動いていれば、パネルだけ起動し直す)
#   ./install.sh --uninstall  外す(動画や再生位置の記録 ~/.local/state/frame-video-player は残す)
set -euo pipefail
name=frame-video-player
opt=$HOME/.local/opt/$name
unit=$name.service
udir=$HOME/.config/systemd/user
src=$(cd "$(dirname "$0")" && pwd)

if [ "${1:-}" = "--uninstall" ]; then
  systemctl --user stop "$unit" 2>/dev/null || true
  systemctl --user disable "$unit" 2>/dev/null || true
  rm -f "$udir/$unit" "$HOME/.local/bin/$name"
  rm -rf "$opt"
  systemctl --user daemon-reload
  echo "外しました(記録は ~/.local/state/$name に残っています)"
  exit 0
fi

mkdir -p "$opt/bin" "$opt/assets" "$udir" "$HOME/.local/bin" "$HOME/Videos"
cp "$src"/frame/*.py "$src/frame/fvp_launcher.c" "$opt/"
cp "$src"/frame/assets/* "$opt/assets/"
# python3 を自分の名前で動かす小さなプログラム(SteamVR に、ほかの python3 のアプリと別のアプリとして見せるため)
gcc -O2 $(python3-config --includes) "$opt/fvp_launcher.c" -lpython3.12 -o "$opt/$name.new"
mv "$opt/$name.new" "$opt/$name"
# YouTube 用の yt-dlp(公式の aarch64 版、1 ファイル)
if [ ! -x "$opt/bin/yt-dlp" ]; then
  curl -fsSL -o "$opt/bin/yt-dlp.new" https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp_linux_aarch64
  chmod +x "$opt/bin/yt-dlp.new" && mv "$opt/bin/yt-dlp.new" "$opt/bin/yt-dlp"
else
  "$opt/bin/yt-dlp" -U >/dev/null 2>&1 || true
fi
cat > "$HOME/.local/bin/$name" <<B
#!/bin/sh
PYTHONHOME=/usr exec "$opt/$name" "$opt/fvp_app.py" "\$@"
B
chmod +x "$HOME/.local/bin/$name"
cat > "$udir/$unit" <<U
[Unit]
Description=frame-video-player (SteamVR dashboard panel 動画プレイヤー)
After=steamvr.service
PartOf=steamvr.service

[Service]
Type=simple
Environment=PYTHONHOME=/usr
ExecStart=%h/.local/opt/$name/$name %h/.local/opt/$name/fvp_app.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=steamvr.service
U
systemctl --user daemon-reload
systemctl --user enable "$unit" >/dev/null
if systemctl --user is-active --quiet steamvr.service; then
  systemctl --user restart "$unit"
fi
echo "入れました。SteamVR のダッシュボードに「動画プレイヤー」が出ます"
