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


## 7. 保护规则（代码层，不靠记性）

六类对象现在由一个共享判定器看管：`scripts/boot-chain-guard.py`。

| 类 | 路径 | 理由 |
|---|---|---|
| 1 | `EFI\boot\bootarm.efi` | 固件直接启动它；替换后连 mass storage 都进不去 |
| 2 | `EFI\boot\BootShim.efi` | 部署工具安装、BCD 指向的 ARM32 shim |
| 3 | `UEFI.elf` | LumiaWoA AArch64 UEFI，被 shim 链式加载 |
| 4 | `EFI\Microsoft\BOOT\BCD` | 解锁后的引导存储；改它曾导致齿轮复位循环 |
| 5 | `EFI\BOOT\BOOTAA64.EFI` | 自定义 UEFI 的入口，本移植加载器 |
| 6 | `EFI\UniXNU\**` | 加载器整棵树；替换其中任一文件都会让 hand-off 证据失效 |

规则只有两条，且没有例外：

1. **创建可以，替换要开口**：目标不存在（空卷首次安装）时允许写入；**替换已存在的受保护对象**必须同时给出
   `--replace-protected` 与一个已存在的备份，否则拒绝。
2. **不允许靠"先删掉再写"或"改哈希基线"绕过**：判定基于路径与"是否已存在"，与文件内容哈希无关；删掉文件只是回到
   "创建"分支，而删除本身需要显式动作并已被文档列为禁止。

### 接线情况（脚本层）

| 脚本 | 现状 |
|---|---|
| `phone-install.py` | 每个 `install()` 调用都带 `replace_protected=args.replace_protected`；**apply 时**受保护替换被拒；dry-run 只提示不改变退出码 |
| `install-native-bringup.py` | 保留原有两道闸：CRITICAL 哈希不符即拒、`EFI/UniXNU` 已存在即拒 |
| `update-native-bringup.py` | 写入集合被限定为 `UPDATABLE`（内核、ADT、LumiaGpuPower.efi、manifest），不含任何受保护对象 |
| `swap-loader.py` | 唯一被允许替换 `BOOTAA64.EFI` 的路径，且自带 `.before-control-mark` 备份与 `--restore` |
| `phone-snapshot.py` / `phone-image.py` | 恢复必须显式给出快照名/镜像路径；不存在"默认用最新"的路径 |

新增两个测试守住这些：
`scripts/test-boot-chain-guard.py`（六类全覆盖、大小写无关、创建 vs 替换、备份缺失即拒、清单含哈希）与
`scripts/test-protection-is-wired.py`（安装器接线、CRITICAL 与 UniXNU 闸门、swap 备份、update 白名单、snapshot 显式命名）。

## 8. 备份baseline：五种东西必须分开命名

以前的文档把这些混在一起，导致"用旧镜像恢复"看起来像安全操作。现在必须区分：

| 类型 | 生成方式 | 覆盖范围 | 是否可作为"当前恢复基线" |
|---|---|---|---|
| **A. 当前 EFIESP 原始镜像** | `phone-image.py dump --volume R:` | 整分区字节 | 仅当与"当前"实测哈希一致时才可（见下） |
| **B. 当前 MainOS 原始镜像** | 同上，MainOS 卷 | 整分区字节 | 同上 |
| **C. 文件级备份** | `phone-snapshot.py save` | 文件与目录结构（含 BCD、bootarm、EFI 树） | 可以，但**会覆盖**受保护文件，必须先 inventory 对比 |
| **D. GPT 分区布局** | 只读枚举（下表） | 分区 GUID/起止 LBA/类型 | 是必需的参照，不参与恢复 |
| **E. 历史快照** | 任意日期留下的 A–C | 那个时点的状态 | **禁止**当作当前基线 |

**明确禁止**：把 `out/phone-backups/unlocked-efiesp.img`（磁盘上 33,554,432 B / `e72bb27d…`）当作当前 EFIESP 的恢复基线——
它的长度与哈希都与其说明文档（16,777,216 B / `1e9b2ff3…`）不符，身份未确认。MainOS 镜像（2,999,971,840 B / `64955e16…`）与记录一致。

### GPT 布局的只读采集（Windows，无需管理员）

```powershell
Get-Disk | Where-Object FriendlyName -match 'Phone' |
  Select-Object Number, FriendlyName, Size, PartitionStyle, Guid |
  Export-Clixml out/phone-backups/gpt-disk.xml
Get-Partition | Where-Object DiskNumber -eq <Number> |
  Select-Object PartitionNumber, DriveLetter, Offset, Size, Type, Guid |
  Export-Clixml out/phone-backups/gpt-partitions.xml
```

这两个文件记录的是 D 类基线；它们**不写手机**，也不含密钥。

## 9. 删除也走同一道门（P1 修复）

`boot-chain-guard.py` 只看“目标是否存在”，因此“先删再建”曾经能绕过替换规则。现在删除与替换共用
`scripts/boot-chain-io.py` 的判定：

| 操作 | 需要的证据 |
|---|---|
| 替换已存在的受保护对象 | `--replace-protected` + `--backup`（存在的文件）+ `--reason` + `--verify` |
| 删除已存在的受保护对象 | `--delete-protected` + `--backup` + `--reason` + `--verify` |
| 在空卷上创建 | 无需（没有可破坏的东西） |

`--replace-protected` 本身**不是**授权：缺任何一项都会被拒。

### 已接线的写入/删除入口

| 脚本 | 现状 |
|---|---|
| `phone-install.py` | 直接调用 `scripts/boot-chain-io.py`；本地弱化版判定已删除；命令行提供 `--backup/--reason/--verify` |
| `update-native-bringup.py` | 释放内核空间的那次 `unlink()` 现在必须 `--delete-protected` + 三项证据 |
| `phone-snapshot.py restore` | 恢复前列出会被覆盖的受保护文件，逐个过守卫；快照自身 manifest **不**被视为当前状态的备份 |
| `swap-loader.py` | 仍然只替换 `BOOTAA64.EFI`，且自带备份与 `--restore` |

`install-native-bringup.py` 的两处删除（临时文件、临时目录）发生在**本机临时树**上，不涉及手机路径。
