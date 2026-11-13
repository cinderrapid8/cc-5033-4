# rawproc — 原始相机资料显影原型

一个零第三方运行依赖（仅 Python 3.11 标准库）的 Bayer RAW 显影链原型。它读取
**自制的原始传感器样本**（小端 uint16 转储 + JSON 元信息），完成逐通道黑电平
扣除、白电平归一、去马赛克与可选白平衡，输出**线性高位深图像**；白平衡与显示
转换是相互独立、可分别检视的步骤，预览曲线不会烘焙进结果。

## RAW 解码依赖升级（rawdecode v1 → v2）

项目唯一的“RAW 解码依赖”是树内版本化解码器包 `rawproc.rawdecode`，不来自任何
包索引；构建锁定见 `requirements-lock.txt`（路径 + 精确版本 + 源码 sha256）与
`pyproject.toml` 的 `[tool.rawproc.raw-decoder]`。

| 契约 | v1（`rawio` 1.0.0，仅保留兼容垫片） | v2（`rawdecode` 2.0.0，当前路径） |
| --- | --- | --- |
| 黑电平 | 松散 dict，调用方按名索引 | `RawLevels` 四通道显式元组；缺任一通道即 `LevelError`，**不以 0 等默认值遮错** |
| 白平衡系数 | 解码器无此契约 | `WhiteBalanceCoeffs` 机内系数 `[r,g,b]`；可整体缺省（记为 `None`），部分给出/非正数即 `WhiteBalanceError`；与显影内核的工作增益严格分离 |
| 有效像素窗口 | 松散 crop 元组 | `ActiveWindow`，解码时证明原点/尺寸落在传感器矩形内，越界即 `WindowError`，适配层切片前再复核一次 |

升级后的代码组织：

```
rawproc/rawdecode/      解码依赖本体（版本 2.0.0）：stream/models/decoder/errors
rawproc/raw_adapter.py  升级适配层：RawFrame → 内核契约，三处接口显式核对、禁止默认值
rawproc/rawio.py        v1 兼容垫片，内部委托 v2，仅供旧调用方与迁移脚本参照
```

**元数据解析成功不等于像素处理正确。** 迁移证据是像素级的，不是“能打开文件”：
`tests/golden/golden_v1.json` 由升级前提交（`edf9d14`）的 v1 管线对
`tests/fixtures/` 下可再分发小样本生成，`scripts/verify_migration.py` 用当前 v2
路径重跑并逐浮点比较马赛克、去马赛克线性 RGB、白平衡线性 RGB，以及过黑/饱和
掩码、有效窗口与黑电平（容差 1e-12，当前 15 组帧×白平衡情形全部精确一致）。
黄金基线可用 `bash scripts/regenerate_golden.sh edf9d14` 从 v1 源码重建。

## 实现范围（明确边界）

- **只实现一种 Bayer 数据布局**：RGGB 家族（2×2 重复 `[[R,G1],[G2,B]]`），
  但支持该布局在传感器网格上的任意 2×2 相位（由元信息 `cfa_origin` 显式给出）。
- 读取小端 `uint16` 传感器转储（dtype `<u2`）。
- **不**解析任何相机厂商专有 RAW（CR2/NEF/ARW/DNG/…），**不**读取、也**不**
  把相机 JPEG 当作 RAW 解码结果。遇到未实现的布局/数据类型会显式报错，而不是
  静默猜测。
- 去马赛克为双线性插值；显示曲线为 sRGB IEC 61966-2-1。

## 图形入口（主要使用方式）

基础显影的图形界面是本地浏览器 GUI，后端只用标准库 `http.server`，控件完全
由基础显影内核驱动（每个请求都实跑 `pipeline.run_pipeline` 的 v2 新路径）：

```bash
# 在项目根目录 rawproc/ 下启动（包以源码方式运行，无需安装）
python -m rawproc.gui                 # 默认 http://127.0.0.1:8765/
python -m rawproc.gui --port 9000 --samples ./samples --outdir ./output
```

打开打印出的 URL 后可：

1. 选择自制原始样本，查看其 CFA 排列、R 像素原点、裁切原点/尺寸、旋转与电平；
2. 调节 R/G/B 线性白平衡增益，或勾选灰世界自动白平衡，点击「显影」；界面显示
   当前 RAW 解码依赖版本（rawdecode 2.0.0）、有效像素窗口、机内白平衡系数与
   本次工作增益，机内系数缺省明确标注为“未声明”，不会伪装成 1,1,1；
3. 在「处理中间结果」中切换查看：原始传感器采样 → 裁切/旋转后传感器 →
   黑扣除+白归一（马赛克）→ 去马赛克（线性）→ 白平衡后线性结果 →
   sRGB 显示预览 → 过黑/饱和标记预览；
4. 点击图像任意像素，检视该像素的 CFA 通道、原始 uint16、归一化值、过黑/饱和
   标记、线性浮点 RGB、16 位编码值与 8 位 sRGB 预览值（均为实际运算结果）；
5. 「保存线性结果与预览」把高位深线性结果与显示曲线预览**分开**落盘，结果 JSON
   记录解码器名称/版本、有效窗口与机内白平衡；
6. 任何异常（坏元信息、缺黑电平通道、越界裁切、非正增益、截断字节流、未知布局
   等）都在界面「异常与提示」区以带解码器版本的文字提示，不会让页面崩溃——
   失败反馈回基础显影内核，而不是在界面里兜底默认值。

## 命令行（仅辅助）

CLI 只镜像基础显影流程，便于脚本与核对，不是主入口：

```bash
python -m rawproc.cli synthesize                 # 生成合成传感器样本
python -m rawproc.cli info samples/handcalc.json # 打印校验后的元信息
python -m rawproc.cli develop samples/chart.json --gains 1.2,1,0.9
python -m rawproc.cli develop samples/chart.json --auto-wb
```

## 颜色位置为何不能按文件宽高猜

CFA 相位由三个元信息共同决定，管线显式追踪，不靠宽高推断：

1. `cfa_origin`：R 像素在传感器网格上的 2×2 相位；
2. `crop_origin`：活动区裁切原点会平移相位（坐标相减后再模 2）；
3. `orientation`：EXIF 1..8 旋转/镜像会交换轴并随帧奇偶改变相位。

`arrayops.transform_cfa_origin` 的映射与实际几何变换逐像素核对，测试覆盖
8 个方向 × 4 个原点 × 多种奇偶尺寸（见 `tests/test_pipeline.py`）。

## 过黑与饱和：保留标记，不先裁成 8 位

- 黑电平可**按通道不同**（`black_levels.r/g1/g2/b`）；白电平也支持逐通道覆盖。
- 原始整数样本 `< 黑电平` 标记为**过黑**，`>= 白电平` 标记为**饱和**。
- 标记在裁切、旋转、去马赛克、保存全过程中保留；归一化值再钳位到 `[0,1]`。
- 线性结果以 **16 位 PNG、16 位 PPM 与 32 位浮点二进制**保存，因此传感器动态
  范围没有被先降采样成 8 位图；8 位 PNG 仅用于预览和掩码。

## 输出文件（结果与预览分开）

| 文件 | 含义 |
| --- | --- |
| `*_linear16.png` / `.ppm` | 16 位线性 RGB，实际运算后取整 |
| `*_linear_float32.bin` | 32 位浮点 planar RGB（小端，前置宽高） |
| `*_preview_srgb8.png` | sRGB 曲线后的 8 位显示预览 |
| `*_preview_linear8.png` | 仅钳位、无曲线的 8 位预览 |
| `*_preview_flags8.png` | 红=饱和、蓝=过黑的标记预览 |
| `*_mask_underblack8.png` / `*_mask_saturated8.png` | 独立掩码 |
| `*_mosaic_gray16.png` | 归一化后的马赛克传感器平面 |
| `*_result.json` | 电平、增益、相位、曲线与文件清单 |

## 合成传感器数据与可手算小图

`python -m rawproc.cli synthesize` 生成 5 个场景（均为真实马赛克 uint16，
不是 JPEG）：

- **handcalc（4×4，可手算）**：黑电平 256/260/256/264，白电平 4096。
  - R：`(1216-256)/3840 = 0.25`
  - G1：`(2178-260)/3836 = 0.5`，G2：`(2176-256)/3840 = 0.5`
  - B：`(3138-264)/3832 = 0.75`
  - 像素 `(0,0)=100` 过黑、`(3,3)=4096` 饱和，验证标记保留。
- **chart**：纯红/纯蓝色块（核对通道归属）、45° 斜边（核对插值产生中间值）、
  1px 高频棋盘（核对去马赛克伪色）、过黑与饱和点。
- **phase**：非零 CFA 原点 + 奇数裁切 + EXIF 6（90°），均匀灰场必须在旋转后
  仍重建为同一灰度，证明相位被追踪。
- **edge45**、**checker**：斜边插值与高频棋盘专项。

## 测试与升级核对

```bash
python3 -I tests/test_pipeline.py        # 旧 20 个测试：迁移后仍在新路径运行到底
python3 -I tests/test_rawdecode.py       # v2 三契约接口与“禁止默认值”测试（20 个）
python3 -I tests/test_upgrade_contract.py# 端到端：版本戳记、白平衡后高位深/颜色（10 个）
python3 -I scripts/verify_migration.py   # v1 黄金参照逐像素/掩码/窗口比对
python3 -I scripts/verify_lock.py        # 解码依赖锁：源码哈希 + 三处版本一致
```

- 旧套件覆盖：手算归一化数值、过黑/饱和标记、双线性插值闭式结果、全方向相位
  几何一致性、纯色通道分离、斜边中间电平、白平衡独立性、16 位 PNG 字节级往返、
  以及未实现布局/越界裁切的元信息拒绝——升级后这些样例仍走真实显影并全部通过。
- 线性像素与有效范围的执行证据：`verify_migration.py` 对每个样本的三种白平衡
  情形比较 7 个平面（马赛克、R/G/B 去马赛克、R/G/B 白平衡线性值）与 2 个掩码；
  过黑（原始整数 < 逐通道黑电平）与饱和（≥ 白电平）在 v1/v2 间逐格一致。
- 仅脚本不算基础显影完成：图形入口 `python -m rawproc.gui` 实跑同一内核，
  界面的增益调节、像素检视与错误回显均由后端真实运算支撑（见上节）。

## 目录结构

```
rawproc/
  rawdecode/     版本化 RAW 解码依赖 v2.0.0（stream/models/decoder/errors）
  raw_adapter.py 升级适配层：黑电平/机内白平衡/有效窗口三契约显式核对
  rawio.py       v1 兼容垫片（委托 v2），保留旧 API 1.0.0 参照
  metadata.py    侧车 JSON 校验与显式相位/电平/裁切/旋转元信息
  arrayops.py    几何变换、EXIF 1..8 与 CFA 相位追踪
  cfa.py         RGGB 索引平面、逐通道黑扣除/白归一、掩码与统计
  demosaic.py    双线性去马赛克（使用显式索引平面）
  color.py       灰世界/手动白平衡、sRGB 与线性预览（相互独立）
  imageio.py     纯标准库 8/16 位 PNG 编码与掩码叠加
  pipeline.py    显影主管线（经适配层走 v2）与结果/预览分存
  synthesize.py  合成传感器样本
  gui.py + web/  本地浏览器图形界面
  cli.py         辅助命令行
scripts/         锁校验、迁移核对、v1 黄金参照再生
tests/           单元/契约/黄金参照测试，fixtures 为可再分发小样本
  golden/        v1 管线生成的旧结果参照（像素级基线）
samples/         生成的自制 RAW + 侧车 JSON
output/          显影结果与预览
requirements-lock.txt / pyproject.toml  构建锁定（解码依赖版本+哈希）
```
