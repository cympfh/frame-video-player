# frame-video-player

Steam Frame の中で動画を見るためのアプリです。SteamVR のダッシュボードに「動画プレイヤー」というパネルが出ます。

## できること

- **Frame の動画**: Frame の `~/Videos` に置いた動画を再生します。
- **PC の動画**: [frame-steamvr-remote](https://github.com/cympfh/frame-steamvr-remote) を入れた PC の「ビデオ」フォルダの動画を、コピーせずにそのまま再生します。
- **YouTube**: PC で動画の URL をコピーし、タスクトレイの frame-steamvr-remote のメニューから「コピーした動画の URL を Frame で再生する」を押すと、Frame で再生が始まります。
- **360° / 180° の動画**: 周りを囲む形で表示します。ファイル名に `360` や `180` が入っていれば自動で切り替わります。パネルの表示ボタンで「平面 / 360° / 180°」を手で切り替えることもできます。
- 続きから再生、音量、10 秒・30 秒の早送りと巻き戻し、字幕 (同じ名前の `.srt` ファイル)、画面の大きさと距離の調整、「正面へ」ボタン。

## 入れ方

Frame のデスクトップモードでターミナル (Konsole) を開いて、次を実行します。

```sh
git clone https://github.com/cympfh/frame-video-player ~/.local/src/frame-video-player
bash ~/.local/src/frame-video-player/install.sh
```

管理者のパスワードは要りません。SteamVR を起動するたびに自動で立ち上がります。

## 自動起動を止める・消す

```sh
systemctl --user disable --now frame-video-player.service   # 自動起動を止める
bash ~/.local/src/frame-video-player/install.sh --uninstall # 消す (再生位置などの記録は ~/.local/state/frame-video-player に残ります)
```

## うまく動かないとき

記録は `~/.local/state/frame-video-player/frame-video-player.log` にあります。

ライセンス: MIT
