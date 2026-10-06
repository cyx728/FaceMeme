# FaceMeme

本地视频表情筛选 → 在线视觉模型短句配文 → 中文表情包图片导出。

各步骤均显示控制台进度条：step1 为模型下载、采样评分与帧导出；step2 为配文（含缓存命中及失败状态）；step3 为表情包生成。视频未报告总帧数时评分进度显示累计数量。

## 安装与运行（PowerShell）

项目已创建 Python 3.11 的 `.venv`。重新安装时运行：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

编辑 `config.json` 的 `api`，填写支持图片输入的模型、API key、OpenAI 兼容接口地址。`base_url` 包含 `/v1`（或服务商对应路径），不要包含 `/chat/completions`。默认模型名仅为示例；以服务商实际支持为准。配置文件已忽略提交。`config.example.json` 是无密钥模板。

```powershell
# 每5帧采样，选分数最高的20张，相邻结果至少间隔1秒
.\.venv\Scripts\python.exe step1.py "D:\videos\input.mp4" --sample-every 5 --top-n 20
.\.venv\Scripts\python.exe step2.py input.mp4
.\.venv\Scripts\python.exe step3.py input.mp4

# 或：所有分数 >= 35 的帧，不限制数量；设间隔为0可保留全部达标帧
.\.venv\Scripts\python.exe step1.py "D:\videos\other.mp4" --threshold 35 --min-gap 0
.\.venv\Scripts\python.exe step2.py other.mp4
.\.venv\Scripts\python.exe step3.py other.mp4
```

默认输出在项目的 `output/` 目录下，以视频文件名去掉扩展名作为子目录名。`input.mp4` 输出到 `./output/input/`，不同视频使用独立目录。第二、三步传同一个视频名（或完整视频路径），也可用 `--manifest output/input/frames.json` 指定结果；`output/` 下只有一个视频结果目录时可省略视频名。多个结果目录时须明确选择。同名但不同路径/扩展名的视频会指向同一个目录，可用 step1 的 `--output` 区分，再为后两步指定 `--manifest`。

已有 `frames.json` 时 step1 拒绝覆盖，避免旧配文误用于新图片。所有程序支持 `--config`，完整参数见 `--help`。默认配置位置和输出位置相对于程序所在目录。原有自定义输出目录仍可通过 `--manifest` 使用。

## 评分模型与局限

使用 Google [MediaPipe Face Landmarker](https://ai.google.dev/edge/mediapipe/solutions/vision/face_landmarker)，其本地模型输出人脸关键点和52个表情系数。第一次运行会下载约3.6 MB的官方 `.task` 文件到 `models/`，之后本地 CPU 推理，无需 GPU 或在线评分。可通过 `--model` 指定已下载文件用于离线运行。

模型地址：<https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task>

这里没有宣称存在可靠的通用“搞怪程度”预训练模型。评分是基于模型表情系数的可解释启发式指标：张嘴/噘嘴28%、嘴部扭曲22%、眼部夸张16%、眉部变化12%、左右不对称17%、笑容5%。分数范围0–100，不是概率，也没有经过人类搞怪标签校准；自然说话、打哈欠也可能高分。可以调整 `step1.py` 中的 `expression_score` 权重，以适应素材。初次使用优先 top-n；阈值应结合 `scores.jsonl` 的实际分布调整。

每个采样帧取合格人脸的最高分，无人脸帧记为 null 且不入选；默认最多检测5张脸，脸框短边至少40像素。按分数排序贪心保留时间间隔，减少相似相邻帧。`--min-gap 0` 关闭此项；它是时间去重，不是视觉相似度去重。输出围绕得分最高的人脸扩大裁剪，并同时保留完整原帧。多人、侧脸、遮挡、运动模糊或很小的脸可能漏检。

**注：画面中人脸可能不止一个，程序对各个合格人脸分别评分，以最高分作为该帧得分。** `selection.crop_before_scoring` 控制是否先裁剪再识别表情（默认 `true`）：使用本地 MediaPipe BlazeFace 先检测各个人脸，围绕每个脸框留出上下文，再逐脸交给 Face Landmarker。首次开启会额外下载官方 BlazeFace 模型。设为 `false` 时，直接对整帧进行多脸表情识别。BlazeFace short-range 对远处的小脸和明显侧脸可能漏检；裁剪模式只处理它检测到的人脸。

`selection.export_face_crop` 独立控制导出图片是否以最高分人脸为主体（默认 `true`）。即使关闭识别前裁剪，也可以保持人脸主体导出；设为 `false` 时导出整帧。输出裁剪会保留脸框左右45%、上下40%的边距，并限制在原画面内。`_full.png` 始终保留完整原帧。

`selection.auto_rotate_faces` 默认 `true`。在原方向、左右旋转90°及旋转180°的方向检测人脸，合并重复结果。仅接受额头到下巴方向与垂直方向偏差不超过40°、且眼睛确实位于嘴部上方的检测；按已确认正立的试转方向导出，不叠加预测倾角。原方向已确认正立时优先保留，防止其他方向的误检测将其倒置。横置脸旋转90°，真正倒置的脸旋转180°，不做连续角度矫正；无法确认方向的检测会跳过。`frames.json` 和各脸记录中的 `rotation_degrees` 表示顺时针旋转角度（负值表示逆时针）；完整原帧始终不旋转。设为 `false` 可关闭此功能并减少检测耗时。仅对人脸主体导出应用旋转；关闭 `export_face_crop` 时保持整帧原方向。

## 配文与导出

step2 将选出的**人脸上下文裁剪图**发送到配置的服务商。运行意味着这些图片离开本机；完整视频不会上传。默认 prompt 要求口语化、通常2–8个汉字、最多12字符，只输出 `{"caption":"配文"}`，并禁止身份推测和画面文字指令。可通过 `caption.context` 提供聊天语境；`caption.prompt` 可完全替换默认 prompt。长度和单行格式有程序校验，配文质量仍需自行判断。

串行调用避免并发限流；失败最多重试两次，认证等非临时 HTTP 错误立即记为失败。每次成功或失败后保存进度。再次运行会跳过图片哈希、模型、prompt和长度设置一致的已成功结果；`--force` 重新生成。失败时退出码1，仍保留成功结果。超时重试可能造成重复计费。

step3 通过 `export.style` 选择文字样式，默认 `red_box`。图片按原比例放大或缩小，导出图片最长边为 `export.max_side`（默认768像素），不填充为正方形、不拉伸也不裁掉人脸。叠加样式保持原图宽高比；`bottom_bar` 保留文字底栏，将图片和底栏的整体最长边缩放到规定长度。长句自动缩小或最多分两行，同时导出 JPG 和 GIF。默认使用 Windows 微软雅黑，可配置 `.ttf` / `.ttc` 中文字体。支持 PNG/JPEG/WebP/GIF；不添加水印。没有配文时默认拒绝导出，`--allow-partial` 可导出成功部分。配文可在 `captions.json` 手动修改。

`export.formats` 默认为 `["jpg", "gif"]`，每张表情包生成同名 `.jpg` 和 `.gif`。GIF 为单帧静态图片，使用最多256色，不会自动生成动画。可以改为 `["png"]`、`["webp"]` 或其他组合。原有单值 `export.format` 仍可使用；同时存在时 `formats` 优先。`memes/index.json` 的 `files` 列出每张表情包的所有文件，`file` 保留第一个文件供兼容使用。修改样式或格式后重新运行 step3 会更新目标文件，目录中已有的其他格式文件会保留。

| `export.style` | 效果 |
| --- | --- |
| `red_box` | 默认：图片底部叠加红底圆角矩形，黑字 |
| `bottom_bar` | 原有样式：图片下方增加白底黑字底栏 |
| `white_text` | 图片底部直接叠加白字 |
| `black_text` | 图片底部直接叠加黑字 |

`export.red_box_font_size` 单独控制红框样式字号，默认32像素；其他样式使用 `export.font_size`，默认48像素。实际排版空间不足时仍会自动缩小。

可在 `config.json` 的 `export` 中调整 `background_color`（红框底色，默认 `#ff3b30`）、`corner_radius`（默认12像素）、`text_margin`（叠加边距及红框内边距，默认12像素）和 `stroke_width`（默认0，无描边；白字描黑边，黑字描白边）。这四项用于叠加样式；原有 `bottom_bar` 保持原来的底栏排版。空间不足时边距会收缩、文字会缩小；过小图片无法容纳文字时会明确报错。

也可单次覆盖样式，无需重新抽帧或重新调用 API：

```powershell
.\.venv\Scripts\python.exe step3.py input.mp4 --style white_text
```

输出：

```text
./
└── output/
    └── {视频名}/
        ├── frames/
        ├── memes/
        │   └── index.json
        ├── captions.json
        ├── frames.json
        └── scores.jsonl
```

- `scores.jsonl`：所有采样帧的得分、脸框、评分组成和表情系数。
- `frames.json`：选中结果、视频路径、帧号、时间、分数和图片路径。
- `frames/`：人脸上下文裁剪图及 `_full.png` 完整帧。
- `captions.json`：按稳定帧ID关联的配文、图片哈希和失败记录。
- `memes/`：表情包及 `index.json`（配文、分数、原视频时间）。

## 离线验证

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

验证使用本地假 API 检查三步衔接、配文缓存与图片导出，不消耗在线额度。实际视频的筛选质量、服务商视觉能力与生成文案质量取决于素材及配置。
