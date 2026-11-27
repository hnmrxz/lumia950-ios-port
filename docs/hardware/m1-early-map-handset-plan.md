# 真机验证：早期标记（`lumia-early-map`）

2026-11-27。**这是准备文档，不是已完成的事**。真机尚未运行这份内核。

## 1. 为什么这件事值得做

QEMU 里已经证明：内核能在 `arm_vm_init` **之前**建立帧缓冲映射、写屏，并且**仍然**跑到 BSD 初始化与 root-wait
（状态码 0，ESR 0，artifact `404140cb…`）。真机的问题恰恰是"卡在 `arm_vm_init` 之前，且屏幕上什么都没有"。
把这条仪器装上手机，**同样的代码路径**会把"卡在哪一段"变成"屏幕上有没有那条色带"。

## 2. 真机与模拟器的差别（必须核对，不能照搬）

| 项 | 真机 | QEMU |
|---|---|---|
| 帧缓冲物理基址 | `0x00400000` | `0xEC7A0000` |
| stride | 4320 | 3200 |
| 分辨率 | 1080×1920 | 800×600 |
| 该基址所在 GB | **与内核镜像同一个 GB**（都 < 1 GB） | 独占一个空 GB |

推论：
- **真机**：identity 表的该 GB 表项**应该已经存在**（start.s 为内核镜像建过），标记只需要补一个**叶子块表项**；
- **QEMU**：该 GB 是空的，标记需要先补一张表。
两条路径都在同一段代码里（先查表项类型，再决定），已在 QEMU 验证过"空 GB"分支；真机走的是"已有表"分支，**尚未实测**。

行范围经 `scripts/test-early-map-arithmetic.py` 对**两种面板**都算过：8–15 行的最后一笔写入都落在被映射的 2 MB 块内。

## 3. 验收（真机）

一次开机即可，判据是**屏幕**，不是日志：

| 观察 | 含义 |
|---|---|
| **屏幕顶部出现一条 8 行的红色色带**，之后无更多输出 | 内核**到达了标记**，但仍在 console 建立之前停下 ⇒ 卡点在 `arm_init` 的标记之后、`PE_create_console()` 之前 |
| 出现色带，**并且**随后出现 `LUMIA: arm_vm_init returned` 与后续日志 | 内核**越过了 VM**，M1 取得真机证据 |
| **没有色带**，屏幕与不带该参数时一致 | 内核**没走到标记**（更早），或标记未安装映射（届时状态码无从读取，只能重复开机确认） |

**色带位置**：Panel 顶部第 8–15 行，宽度为整行宽度。颜色 `0x00E03030`（BGR 下呈红色）。

## 4. 前置条件与回滚

1. 手机 EFIESP 与 MainOS 的**成对**镜像仍在（`docs/hardware/boot-chain-preservation.md` 的 A/B 类基线）；
2. 只替换 `EFI\UniXNU\Payloads\kernel.macho`（`updatable` 白名单内），**不动**六类受保护对象；
3. `unixnu.toml` 的 `args` 追加 `lumia-early-map`（改它要过 `scripts/boot-chain-io.py` 的四项证据）；
4. 回滚：把 `kernel.macho.prev` 换回，并删掉 `args` 里那一项；
5. 若屏幕完全无变化，**不要反复刷**：先确认参数确实生效（`.txt` 记录、`DEPLOYED.txt` 哈希）。

## 5. 操作顺序（每步都可停下）

1. 备份当前 `kernel.macho` 与 `unixnu.toml` 到 `out/phone-backups/`；
2. 部署新内核 + 参数；
3. 开机，等 90 秒，**拍照**；
4. 记录：kernel 哈希、`args` 原文、照片；
5. 若照片显示色带 ⇒ 把"卡点在标记之后"写进 `docs/hardware/measurements/`；
6. 若无色带 ⇒ 记录为"更早"，并为下一步（更早的观测点）重新规划。

## 6. 明确禁止

- 为这次验证格式化 MainOS、重排分区、写 eMMC；
- 更换 `BootShim.efi`、`UEFI.elf`、`BCD`、`BOOTAA64.EFI`；
- 在没有照片的情况下把任何一步写成"已验证"。

## 7. 自我测试已覆盖真机分支（2026-11-27）

`lumia-early-map-selftest` 在 QEMU 上跑过真机将要走的那条分支（帧缓冲所在 GB 的 identity 表项**已经是表**），
结果状态 **30**：走的是"已有表"分支、哨兵完好、内核仍到 root-wait。

因此真机验证时，**分支风险已降低**，剩下的风险是数值（真机 stride/行范围，已由 `scripts/test-early-map-arithmetic.py` 对两种面板验算）
与真机硬件本身。

## 8. 一条命令完成部署（`scripts/deploy-early-map.py`）

手机接上后，部署不再是手工步骤，而是一个带闸门的脚本：

```
# 预演（默认）：只报告会改什么，不写任何东西
python scripts/deploy-early-map.py --efiesp R: --kernel out/earlymap/mach.development.bcm2837.unstripped

# 实做：保留被替换的内核，并走 boot-chain 闸门
python scripts/deploy-early-map.py --efiesp R: --kernel out/earlymap/mach.development.bcm2837.unstripped     --expect-sha256 717752f741d8597fcf1f497b964ba3a0d27da55978cf197a261d9e617da1e8f0     --apply --backup out/phone-backups/kernel.before
```

它做的事与拒绝条件：

| 步骤 | 拒绝条件 |
|---|---|
| 核对工件 SHA-256 | `--expect-sha256` 不匹配 ⇒ 退出 1 |
| 确认手机是这条链 | 没有 `EFI/UniXNU/unixnu.toml` ⇒ 退出 2 |
| 替换 `kernel.macho` | 目标已存在而没给 `--backup` ⇒ 退出 1 |
| 受保护对象闸门 | `boot-chain-io` 的四项证据缺一 ⇒ 退出 1 |
| 追加启动参数 | `args` 里已有该 token ⇒ 不重复追加 |
| 写入后校验 | 目标哈希与工件不符 ⇒ 退出 1 |

`test-deploy-early-map.py`（7 条）覆盖：dry run 不写、缺备份被拒、缺闸门被拒、齐备则写入并把旧内核留到备份、
token 只加一次、哈希不符被拒、非本链条的手机被拒。
