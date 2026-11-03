# frame-video-player

Steam Frame の中で動画を見るためのアプリです。SteamVR のダッシュボードに「動画プレイヤー」というパネルが出ます。

## できること

- Frame の `~/Videos` に置いた動画を再生します (「Frame の動画」タブ)。
- [frame-steamvr-remote](https://github.com/cympfh/frame-steamvr-remote) を入れた PC の動画を、コピーせずにそのまま再生します (「PC の動画」タブ)。どのドライブのどのフォルダでも開けます。最近開いたフォルダは上のボタンからすぐ開けます。
- YouTube の動画を再生します。PC で動画の URL をコピーし、タスクトレイの frame-steamvr-remote のメニューから「コピーした動画の URL を Frame で再生する」を押します。そのあと Frame のパネルの「YouTube」タブで「PC から URL を受け取る」を押すと再生が始まります。
- 360° と 180° の動画は、周りを囲む形で表示します。ファイル名に `360` や `180` が入っていれば自動で切り替わります。「表示」ボタンで平面・360°・180° を、「3D」ボタンで左右・上下に並んだ立体動画かどうかを手で切り替えられます。
- 続きから再生、音量、10 秒・30 秒の早送りと巻き戻し、字幕 (同じ名前の `.srt` ファイル)、画面の大きさと距離の調整、360° と 180° で見る向きを回す「◀」「▶」(30° ずつ) と「正面へ」ボタン。
- 寝そべって見ることもできます。上 (や下) を向いた状態で「正面へ」や大きさ・距離のボタンを押すと、平面動画の画面は視線の真正面に、こちらを向いて置かれます。座って使うときは従来どおり、床に立てた正面の壁に置かれます。
- 再生中にメニュー (ダッシュボード) を開いている間は、メニューと動画画面の両方が透けます (75%)。どちらも見えたまま操作できます。

## 操作

- 操作はレーザーポインターだけです。パネルのボタンを押す、シークバーを押す、一覧をスクロールする、で使います。
- コントローラーのボタンやスティックには何も割り当てていません。メニューの開け閉めで再生や一時停止が切り替わることもありません。

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
