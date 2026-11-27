# 保护现有启动链：文件清单、禁改项与回滚

只读审计，日期 2026-11-27。**本文件不授权任何写操作**：它记录哪些文件必须原样保留、当前实测值是多少、以及一旦误改如何回滚。

## 1. 链的形状（真机实测）

```
stock firmware (secure boot on)
  -> EFI\boot\bootarm.efi        ARM32 Windows Phone boot manager（解锁后由它找 UEFI.elf）
  -> \UEFI.elf                   LumiaWoA/Lumia950XLPkg AArch64 UEFI
  -> EFI\BOOT\BOOTAA64.EFI       自定义 UEFI 启动的入口（本移植的加载器）
  -> EFI\UniXNU\UniXNU.efi + unixnu.toml + Drivers\DarwinBoot.efi (+ ntfs.efi)
  -> EFI\UniXNU\Payloads\kernel.macho (+ .adt)，当前位于 MainOS（NTFS）
```

真机证据：菜单启动、`DARWINBOOT: hand-off to the kernel`、`hand-off` 页 + EL1 寄存器（`docs/hardware/measurements/handoff-hardware/`、`docs/hardware/measurements/register-probe/`）。

## 2. 文件清单与实测值

"本轮实测"指 2026-11-27 本次会话从手机的 mass-storage 卷上读到的值；手机随后断开，**其余项目未再复核**。

| 文件 | 大小 | SHA-256（本会话实测） | 说明 |
|---|---|---|---|
| `EFI\boot\bootarm.efi` | 870,856 | `f259543a94258db63d946fa2972a36acb44ca5526b614ece982932467428aab0` | **原机 ARM32 Boot Manager，绝对不能替换** |
| `EFI\boot\BootShim.efi` | 53,744 | `3b3c7a7f676c297b6035d63b2e3630e012d6223ab9ebb3ab36b76e9884531a3d` | ARM32（PE machine 0x01C4, subsystem 16），当前链使用 |
| `EFI\BOOT\BOOTAA64.EFI` | 94,208 | `9d9311b39a252861…` | 本移植加载器（AArch64, subsystem 10） |
| `EFI\UniXNU\UniXNU.efi` | 94,208 | 与 `BOOTAA64.EFI` 同一文件（CI 校验项） | 加载器本体 |
| `EFI\UniXNU\Drivers\DarwinBoot.efi` | 26,624 | `32965db888c8bcfe…`（CI 检查输出） | 读内核 + ADT 并 hand-off |
| `EFI\UniXNU\Drivers\ntfs.efi` | 61,440 | 本次未读 | MainOS 读取所依赖 |
| `EFI\UniXNU\unixnu.toml` | 2,484（当前） | 本次未记 | 菜单与 `args` |
| `\UEFI.elf` | 本次未读 | 本次未读 | LumiaWoA AArch64 UEFI |
| `EFI\Microsoft\BOOT\BCD` | 28,672（本次列目录所得） | 本次未读 | **不得修改** |

## 3. 绝对不能替换 / 修改的文件

1. **`EFI\boot\bootarm.efi`** —— 固件直接启动它；它也是 mass storage 模式的提供者。替换它会让手机连 mass storage 都进不去。
2. **`\UEFI.elf`** —— 部署工具安装、并其 shim 链式加载的那一份。仓库脚本带 `--keep-uefi-elf` 就是为了不覆盖它。
3. **`EFI\Microsoft\BOOT\BCD`** —— 解锁后的 boot 配置。历史教训：把 `{default}` 指向别的加载器会让管理器退回 Windows reset 流程（两只齿轮）。
4. **已通过真机验证的 `EFI\UniXNU\*`** —— 任一文件被替换后，必须重新取得一次真机 hand-off 证据才算验证通过。

## 4. 与旧记录的三处不一致（必须以此为准）

| 项 | 旧记录 | 本会话实测 | 结论 |
|---|---|---|---|
| `bootarm.efi` | `install-native-bringup.py` 的 CRITICAL 期望 `e0034756…` | `f259543a…`（870,856 B） | **CRITICAL 表已过期**；安装脚本会因此拒绝执行（安全，但也意味着不能直接用） |
| `BOOTAA64.EFI` | CRITICAL 期望 `b782ee89…`（WOA 原始） | `9d9311b3…`（本移植加载器） | 同上；被测链已不再是"WOA 原始态" |
| EFIESP 原始镜像 | `2026-11-25-unlocked-partition-images.md` 记 16,777,216 B / `1e9b2ff3…` | 磁盘上 `unlocked-efiesp.img` 为 **33,554,432 B / `e72bb27d…`** | **文档数字与文件不符**；恢复前必须重新核对 |
| MainOS 原始镜像 | 2,999,971,840 B / `64955e16…` | 与记录**一致** | 可用 |

> 结论：**当前 EFIESP 上的实际文件已不是 2026-11-25 快照时的状态**（BCD 从 24,576 B 变成 28,672 B 就是一例）。
> 因此"恢复 11-25 快照"不是安全操作，除非确认你要回到的正是那个状态。

## 5. 回滚手段（按侵入性排序）

| 手段 | 覆盖范围 | 证据状态 |
|---|---|---|
| `scripts/phone-snapshot.py restore --efiesp R: --name <快照>` | EFIESP 上的文件（含 BCD、bootarm、EFI 树） | 机制存在；**恢复 11-25 快照会连 bootarm/BCD 一起回退** |
| `scripts/swap-loader.py --restore` | 只回滚 `EFI\BOOT\BOOTAA64.EFI` 一个文件（备份 `BOOTAA64.EFI.before-control-mark`） | 本轮已用过，成功 |
| `scripts/phone-image.py restore --partition EFIESP/MainOS --image … --apply` | 整分区原始镜像（flash 模式） | 机制存在；文档明写"两个分区必须一起恢复"；**EFIESP 镜像数字与文档不符**，恢复前须重核 |
| `scripts/phone-recover.ps1`（FFU） | 整机 | 最后手段，需要厂商工具重新解锁 |

## 6. 给后续操作的硬性要求

1. 任何写操作前，先 `scripts/phone-snapshot.py save`（文件级）+ `scripts/phone-image.py dump`（分区级），并把备份**放到手机以外**的介质。
2. 不运行 `install-native-bringup.py` / `phone-install.py` 的 `--apply`：前者会因 CRITICAL 过期而拒绝（安全），后者在 `--uefi-elf`/`--bootshim` 默认路径下**会写**受保护文件。
3. 若确需重新基线 CRITICAL 表，必须把"当前真机实测值 + 一次成功的真机 hand-off 证据"一起提交，不能只改数字。
4. 替换 `BOOTAA64.EFI` 类试验一律用 `swap-loader.py`（自带备份与 `--restore`），不要手工覆盖。
