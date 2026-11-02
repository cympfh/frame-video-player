# frame-video-player

Steam Frame の中で動画を見るためのアプリです。SteamVR のダッシュボードに「動画プレイヤー」というパネルが出ます。

## できること

- Frame の `~/Videos` に置いた動画を再生します (「Frame の動画」タブ)。
- [frame-steamvr-remote](https://github.com/cympfh/frame-steamvr-remote) を入れた PC の「ビデオ」フォルダの動画を、コピーせずにそのまま再生します (「PC の動画」タブ)。
- YouTube の動画を再生します。PC で動画の URL をコピーし、タスクトレイの frame-steamvr-remote のメニューから「コピーした動画の URL を Frame で再生する」を押します。そのあと Frame のパネルの「YouTube」タブで「PC から URL を受け取る」を押すと再生が始まります。
- 360° と 180° の動画は、周りを囲む形で表示します。ファイル名に `360` や `180` が入っていれば自動で切り替わります。「表示」ボタンで平面・360°・180° を、「3D」ボタンで左右・上下に並んだ立体動画かどうかを手で切り替えられます。
- 続きから再生、音量、10 秒・30 秒の早送りと巻き戻し、字幕 (同じ名前の `.srt` ファイル)、画面の大きさと距離の調整、「正面へ」ボタン。

## コントローラーのスティック

- パネルを指しているとき、右スティックの上下で動画の一覧が動きます。
- 再生中は、パネルを開いていなくても次のように使えます。
  - 左スティックの左右: 10 秒ずつ早送り・巻き戻し。倒したままだと続けて進み、長く倒すと 30 秒ずつになります。
  - 左スティックの押し込み: 一時停止と再生。
  - 右スティックの左右 (360° と 180° のときだけ): 見ている向きを回します。
- VRChat などのゲームも同じスティックを使うので、再生中はアバターも一緒に動きます。気になるときは、パネル右上の「スティック操作」を「切」にしてください。360° と 180° の再生中は、SteamVR の設定の開発者向けの項目で「Experimental overlay input overrides」を入れると、スティックがこのアプリだけに届きます (ゲームではアバターが動かなくなります)。
- 割り当ては SteamVR の「コントローラー設定」から変えられます。

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
