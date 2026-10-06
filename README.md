# FaceMeme

把视频里夸张、有趣的人脸表情做成可直接发到聊天里的表情包：自动挑选画面，生成简短中文配文，再导出带文字的 JPG 和 GIF。支持 Windows 和 macOS，三个步骤都有控制台进度条。

## 快速开始

先从 [Python 官网](https://www.python.org/downloads/) 安装 **Python 3.11（推荐）或3.12**。Windows 安装时勾选 **Add Python to PATH**。首次需要联网下载依赖和本地人脸模型，并准备支持图片输入的在线模型 API。

1. 把视频放到项目的 `input/` 文件夹，可以放多个。
2. 起不同的名字，如 `朋友聚会.mp4`、`课堂瞬间.mov`。不要让两个视频只有扩展名不同；输出目录使用不含扩展名的视频名。
3. Windows 双击 **run_windows.bat**；macOS 在项目目录打开终端，运行 **bash run_macos.command**。
4. 按提示填写 API 基础地址、密钥和视觉模型名。其余配置自动补全；密钥输入隐藏，保存在本机 `config.json`。
5. 等待完成，到 `output/{视频名}/memes/` 取表情包。每张默认生成 JPG 和静态 GIF。

以下是从放置视频、重命名到默认运行的完整命令。先进入项目目录，将示例视频路径换成自己的路径。

**Windows · PowerShell**

```powershell
New-Item -ItemType Directory -Force input | Out-Null
Copy-Item "D:\我的视频\原视频.mp4" "input\聚会.mp4"
# 如需再次改名，保留实际扩展名：
Rename-Item "input\聚会.mp4" "朋友聚会.mp4"
.\run_windows.bat
```

**macOS · 终端**

```bash
mkdir -p input
cp "$HOME/Movies/原视频.mp4" "input/聚会.mp4"
# 如需再次改名，保留实际扩展名：
mv "input/聚会.mp4" "input/朋友聚会.mp4"
bash run_macos.command
```

macOS 若希望双击启动，先执行一次 `chmod +x run_macos.command`。如果系统限制双击运行，直接用上面的 `bash` 命令。

一键入口先检查配置，再创建/检查 `.venv`、安装依赖，最后依次处理 `input/` 顶层所有视频。支持 MP4、MOV、MKV、AVI、WebM、M4V、MPEG、MPG、WMV、FLV、MTS、M2TS；实际解码能力取决于编码。中文和含空格的路径也可使用。

配文会将选中的人脸裁剪图发送到配置的 API 服务商，并产生服务商费用；完整视频不上传。`config.json`、输入视频、模型和输出目录已从 Git 排除。

## 输出与再次运行

```text
FaceMeme/
├── input/
│   ├── 朋友聚会.mp4
│   └── 课堂瞬间.mov
└── output/
    ├── batch_report.json
    └── 朋友聚会/
        ├── frames/             # 裁剪图及 _full.png 完整原帧
        ├── memes/              # JPG、GIF、index.json
        ├── captions.json
        ├── frames.json
        ├── scores.jsonl
        └── batch_state.json    # 一键入口续跑依据
```

再次运行会复用同一视频、同一筛选配置和同一 step1 代码生成的完整抽帧结果，跳过已成功且配文配置未变的 API 请求，再导出图片。视频内容、筛选配置或 step1 代码变化时，创建 `{视频名}_{时间戳}` 新目录；手动生成且无 `batch_state.json` 的旧结果也不会覆盖。后续可续跑匹配的新目录。

一个视频失败后继续处理下一个。部分配文失败时导出成功部分，并在 `output/batch_report.json` 标为 `partial`；重跑补做失败配文。批次全部成功退出码0，失败或部分成功为1，中断为130。Ctrl+C 中断后保留已保存结果。无视频时提示放入文件，不调用 API。

## 运行命令与配置

### 一键入口参数

两个系统的参数相同：

```powershell
# Windows：仅补全和检查配置，不安装依赖、不处理视频
.\run_windows.bat --check-config
# 非交互：错误配置直接报错
.\run_windows.bat --non-interactive
# 指定视频目录和配置
.\run_windows.bat --input "D:\videos" --config config.json
```

```bash
# macOS
bash run_macos.command --check-config
bash run_macos.command --non-interactive
bash run_macos.command --input "$HOME/Movies" --config config.json
```

向导保留已有配置，用 `config.example.json` 默认值补齐缺项。字段不合法时列出字段名，可以输入如 `selection.top_n` 并填新值；输入 `q` 退出后自行编辑。JSON 语法损坏不会被覆盖。配置检查不发付费测试请求；模型是否支持图片需由服务商确认。

### config.json 常用设置

配置使用双引号，不支持注释，末尾字段不要加逗号。现有配置会保留，下面是模板默认值。

| 字段 | 用途 / 默认值 |
| --- | --- |
| `api.base_url` | 基础地址，如 `https://api.openai.com/v1`；不要含 `/chat/completions` |
| `api.api_key` / `api.model` | 密钥 / 支持图片的模型名；模板模型仅为示例 |
| `api.timeout_seconds` / `max_retries` | 请求超时90秒 / 最多重试2次 |
| `selection.sample_every` | 每5帧采样，1表示每帧 |
| `selection.top_n` | 最高分20帧；threshold 非 null 时不生效 |
| `selection.threshold` | 默认 null；设0–100数字选择所有达标帧 |
| `selection.min_gap_seconds` | 结果至少间隔1秒；0关闭时间去重 |
| `selection.max_faces` / `min_face_size` | 每帧最多5张脸 / 脸框短边至少40像素 |
| `selection.crop_before_scoring` | true，先逐脸裁剪再评分 |
| `selection.export_face_crop` | true，人脸主体导出；false为整帧 |
| `selection.auto_rotate_faces` | true，横置人脸图自动转正 |
| `caption.max_chars` | 配文最多12字符 |
| `caption.context` / `prompt` | 补充聊天语境 / 完整替换默认 prompt；默认空字符串 / null |
| `export.style` | 默认 red_box，见下表 |
| `export.max_side` | 最长边768，保持比例，不填充为正方形 |
| `export.formats` | 默认 `["jpg", "gif"]`；支持 png/jpg/jpeg/webp/gif |
| `export.red_box_font_size` / `font_size` | 红框独立字号32 / 其他样式48像素 |
| `export.font_path` | null 自动选择 Windows 微软雅黑或 macOS 中文字体；可填 .ttf/.ttc 路径 |
| `export.background_color` | 红框底色 `#ff3b30` |
| `export.corner_radius` / `text_margin` | 圆角12 / 边距12像素 |
| `export.stroke_width` | 0无描边；白字描黑边，黑字描白边 |

| style | 效果 |
| --- | --- |
| `red_box` | 图片底部叠加红底圆角矩形和黑字 |
| `bottom_bar` | 图片下方增加白底黑字文字栏 |
| `white_text` | 图片底部直接叠加白字 |
| `black_text` | 图片底部直接叠加黑字 |

叠加样式保持原图宽高比；底栏样式将图片与文字栏整体缩放到指定最长边。长句缩小或最多分两行。GIF 为单帧静态图片，最多256色。旧的其他格式文件不会自动删除，`memes/index.json` 的 `files` 列出本轮生成文件。旧版 `export.format` 仍支持，同时存在时 `formats` 优先。

### 单独执行每一步

一键入口安装环境后，使用以下命令，无需激活 venv。

**Windows**

```powershell
.\.venv\Scripts\python.exe step1.py "input\朋友聚会.mp4"
.\.venv\Scripts\python.exe step2.py "朋友聚会.mp4"
.\.venv\Scripts\python.exe step3.py "朋友聚会.mp4"
# 只换样式，不重新调用 API
.\.venv\Scripts\python.exe step3.py "朋友聚会.mp4" --style white_text
```

**macOS**

```bash
.venv/bin/python step1.py "input/朋友聚会.mp4"
.venv/bin/python step2.py "朋友聚会.mp4"
.venv/bin/python step3.py "朋友聚会.mp4"
.venv/bin/python step3.py "朋友聚会.mp4" --style white_text
```

其他参数如下，Windows 将 `.venv/bin/python` 换成 `.\.venv\Scripts\python.exe`：

```bash
# 更密集采样，只选10张，间隔2秒
.venv/bin/python step1.py "input/朋友聚会.mp4" --sample-every 2 --top-n 10 --min-gap 2 --output output/聚会精选
# 全部评分 >=35 的采样帧，关闭时间去重
.venv/bin/python step1.py "input/朋友聚会.mp4" --threshold 35 --min-gap 0 --output output/聚会阈值
# 自定义目录须向后两步指定 manifest
.venv/bin/python step2.py --manifest output/聚会精选/frames.json
.venv/bin/python step3.py --manifest output/聚会精选/frames.json
# 重做所有配文；导出成功部分；指定配置及字体
.venv/bin/python step2.py "朋友聚会.mp4" --force
.venv/bin/python step3.py "朋友聚会.mp4" --allow-partial
.venv/bin/python step3.py "朋友聚会.mp4" --config config.json --font "/path/to/chinese.ttf"
```

`--top-n` 与 `--threshold` 互斥，命令行优先于配置。手动 step1 不覆盖已有 `frames.json`，需改 `--output`。第二、三步可传视频路径、视频名或 `--manifest`；output 下只有一个结果目录时可省略视频名。所有程序支持 `--help`。

## 常见问题

- **找不到 Python或版本不支持：** 安装3.11或3.12，重开终端。项目所用 MediaPipe 不按 Python 3.14 配置。
- **从 Windows 搬到 Mac 后 .venv 报错：** 虚拟环境不能跨系统使用，将 `.venv` 改名为备份后重新启动，入口会重建。
- **安装或下载失败：** 检查网络、代理和磁盘空间，再次启动。入口不绕过系统代理，成功安装后不重复安装。
- **API 401/403、429或模型不支持图片：** 核对密钥、额度、地址和模型；失败记录见 captions.json。临时错误会重试，超时重试可能重复计费。
- **字体找不到：** 将 font_path 设为 null，或填写本机中文字体路径。向导会辅助修正跨系统旧字体路径。
- **重复视频名：** 重命名视频，保留真实扩展名；不要用改扩展名伪装视频格式。
- **重新筛选或换样式：** 改筛选配置后运行一键入口；只改样式、尺寸或格式可直接重跑 step3。

## 技术方法与限制

### 本地表情评分

使用 Google [MediaPipe Face Landmarker](https://ai.google.dev/edge/mediapipe/solutions/vision/face_landmarker)，输出人脸关键点和52个表情系数。首次下载官方 Face Landmarker 和 BlazeFace short-range 模型到 models，之后本地 CPU 推理，无需 GPU。step1 的 `--model` 可指定已有 .task 文件。

“搞怪评分”为启发式指标，不是校准过的人类幽默评分或概率：张嘴/噘嘴28%、嘴部扭曲22%、眼部夸张16%、眉部变化12%、左右不对称17%、笑容5%，范围0–100。说话、打哈欠也可能高分。可调整 step1 的 expression_score 权重；初次优先 top-n，阈值参考 scores.jsonl 分布。

**画面可能包含多张人脸。** 程序逐脸评分、帧得分取最高值；无人脸帧记 null且不入选。按分数贪心保持时间间隔，这是时间去重而非视觉去重。人脸导出左右扩展45%、上下40%边距，限制在原图内，另保留完整原帧。小脸、侧脸、遮挡和模糊可能漏检。

自动旋转在0°、左右90°、180°检测并合并重复脸，只接受额头至下巴轴线偏差不超过40°、眼睛位于嘴部上方的结果。原方向已正立时优先保留，不叠加预测倾角；无法确认朝向则跳过，不做连续角度矫正。rotation_degrees 为顺时针角度，负数为逆时针。整帧导出及完整原帧不旋转。多方向检测增加耗时，模型仍可能误判。

### 在线配文与结果关联

step2 使用 OpenAI 兼容 `/chat/completions` 图片输入。默认 prompt 要求口语化、通常2–8汉字、最多12字符，只返回 `{"caption":"配文"}`，不猜身份、不执行图片文字指令。程序校验 JSON、单行和长度；文案质量仍需自行判断。

请求串行运行，每次保存进度；图片哈希、模型、API 地址、prompt和字符上限一致时复用成功配文。step3 检查图片哈希避免配文错配。可手动修改 captions.json 的文字再导出。认证等非临时错误不重试。

scores.jsonl 保存各采样帧评分、脸框、表情系数；frames.json 保存入选帧ID、时间、分数、图片路径和旋转角度；captions.json 保存文字及失败记录；memes/index.json 保存导出文件、短句、分数和原视频时间。batch_state.json 记录视频哈希、筛选配置及 step1 代码版本；batch_report.json 汇总一键执行状态。

### 离线验证

```powershell
# Windows
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

```bash
# macOS
.venv/bin/python -m unittest discover -s tests -v
```

离线测试使用假 API，不消耗在线额度。实际筛选和配文质量取决于素材、模型及配置。
