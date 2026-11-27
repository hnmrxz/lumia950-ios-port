# microSD 载荷实验：设计、验证步骤、失败条件与回滚

只读设计文档，2026-11-27。**不在手机上执行任何写入**；这里定义的是"等到要验证时怎么做"，以及失败时怎么退回。

## 1. 为什么要做这个实验

当前 DarwinBoot 从 **MainOS（NTFS）** 读 `EFI\UniXNU\Payloads\kernel.macho(+.adt)`，真机已验证 hand-off。若将来要动
MainOS（新分区/新文件系统），必须先证明**另一条读取路径**成立，而且最好完全不动现有分区。

microSD 是唯一"零分区改动"的候选。

## 2. 现状（未验证部分必须标明）

| 能力 | 现状 | 依据 |
|---|---|---|
| UEFI 枚举 microSD | **未验证** | 无真机记录；需要一次插卡观察菜单是否出现新卷 |
| UniXNU 访问 microSD 文件系统（FAT32） | **未验证**；仓库有 FAT 支持但未经此路径实测 | `payload`/`UniXNU` 只验证过 FAT/EFI 系统分区与 NTFS |
| DarwinBoot 从指定卷读 kernel/ADT | 部分：代码按 `unixnu.toml` 的条目路径读取；**是否支持任意卷前缀未确认** | 现有成功案例都是 MainOS |
| 需要 EFI 驱动 | 若卡为 FAT32，通常**不需要**额外驱动（UEFI 自带 FAT） | 通用 UEFI，但需实测 |
| 失败会不会影响现有分区 | 若只改菜单条目并在 ESP 之外放文件，**可完全不影响** | 见第 5 节 |

> 上述"未验证"在真机取证之前**不得**升级为已验证；本实验设计的目的就是把它们变成可判定的问题。

## 3. 准备（不接触手机）

1. 一张 microSD，格式化为 **FAT32**，创建目录：
   ```
   \EFI\UniXNU\Payloads\kernel.macho
   \EFI\UniXNU\Payloads\kernel.macho.adt
   ```
   内核与 ADT 取当前真机在用的同一份（`DEPLOYED.txt` 记录其 SHA-256）。
2. 在仓库侧准备菜单条目：**复制**现有 `xnu` 条目为 `xnu-sd`，只改卷/路径，不动原条目。
3. 记录"改动前后"的清单：
   ```
   python scripts/boot-chain-guard.py inventory --root R: --out out/phone-backups/chain-before.json
   ```
4. 确认回滚材料齐备：`R:\EFI\UniXNU\unixnu.toml` 原文件复制一份到 `out/`（**不要**只留在手机上）。

## 4. 验证步骤（每一步都有成败判据）

| 步 | 动作 | 通过判据 | 失败判据 |
|---|---|---|---|
| 1 | 插卡、开机、停在菜单 | 菜单正常出现（说明 UEFI 未被卡影响） | 菜单不出现/卡死 → **立即拔卡**，回到第 5 节 |
| 2 | 观察菜单是否列出新卷条目 | 能看到 `xnu-sd` 条目且卷可被枚举 | 看不到 → 记录"UEFI 未枚举 microSD"，实验中止 |
| 3 | 选择 `xnu-sd` 启动 | 出现 `DARWINBOOT: payload from another volume` 一类日志 | 报 "payload not found" → 记录卷/路径问题 |
| 4 | 观察 hand-off 页 | 打印 `kernel va/pa`、`entry words 140006F5`，与 NTFS 路径一致 | 停在菜单/DarwinBoot 报错 |
| 5 | 拍屏幕取证 | 照片 + `report.json` 存档 | — |

**判据的严格性**：第 3、4 步必须出现与当前 NTFS 路径**同形**的日志；只"能启动到菜单"不算通过。

## 5. 失败条件与回滚

| 失败 | 现象 | 回滚 |
|---|---|---|
| UEFI 被卡影响 | 菜单不出现 | **拔卡 + 断电重启**（microSD 不参与固件启动，拔掉即恢复） |
| UniXNU 读不到卷 | 菜单有条目但读文件失败 | 从 `unixnu.toml` 删掉 `xnu-sd` 条目；原条目未改动，故开机仍走 NTFS |
| DarwinBoot 读不到内核 | 日志报 not found | 同上 |
| 误改到受保护文件 | — | `python scripts/swap-loader.py --restore`（仅 BOOTAA64.EFI）或从 `out/` 的 toml 副本恢复 |

**前置保险（必须做）**：改 `unixnu.toml` 之前把它复制到 `out/phone-backups/`，并在改完后用
`boot-chain-guard.py inventory` 复核受保护对象哈希未变（`unixnu.toml` 本身属于受保护树，改动必须被记录）。

## 6. 与"MainOS 替换"的关系

- 本实验**不改变** MainOS，也不改变 EFIESP 的启动文件；它只新增一个菜单条目。
- 若第 2 步通过（UEFI 能枚举 microSD），则"换卷"这条路可行，`docs/hardware/mainos-replacement-readiness.md` 的阶段 1 可以落地；
- 若第 2 步失败，则说明 microSD 不可用作载荷卷，MainOS 的 NTFS 路径在可预见期内**不可替代**，也就更不能格式化 MainOS。

## 7. 明确禁止

1. 为这个实验格式化或重排 MainOS；
2. 替换 `bootarm.efi` / `UEFI.elf` / `BCD` / `BOOTAA64.EFI`；
3. 在没有拍照取证前，把上述任何一步写成"已验证"。


## 8. 修正：这不是"零写入实验"，必须分两阶段

`unixnu.toml` 位于 `EFI\UniXNU\`，属于第六类受保护对象。因此"新增 `xnu-sd` 条目"**不是**只读操作，也不能只靠拔卡回滚。

### 阶段 A：纯只读探测（不改任何文件）

| 动作 | 观察到什么 | 是否写入手机 |
|---|---|---|
| 插入 microSD（FAT32，内容见第 3 节），开机停在菜单 | 菜单是否出现新卷/新条目；UEFI 是否枚举到设备 | **否** |
| 不选择任何新条目，直接让原 `xnu` 条目启动 | 原有 NTFS 路径是否仍 hand-off（回归确认） | 否 |

阶段 A 的结论只有两种：**UEFI 能看到该卡**，或**看不到**。看不到就停止，不必进入阶段 B。

### 阶段 B：受控的菜单配置实验（需要一次受保护的 EFIESP 写入）

前置条件（缺一不可）：

1. 阶段 A 已确认 UEFI 能枚举该卡；
2. 先做**文件级快照**：`python scripts/phone-snapshot.py save --efiesp R: --out out/phone-backups`；
3. 记下当前 `unixnu.toml` 的 SHA-256，并在改完后与 `scripts/boot-chain-guard.py inventory` 对照；
4. 修改必须通过守卫：`--replace-protected --backup <快照里的 unixnu.toml> --reason ... --verify ...`；
5. **保留原 `xnu` 条目**，只新增 `xnu-sd`；这样即使新条目完全失败，菜单仍能用原条目启动；
6. 改完立刻用原 `xnu` 条目启动一次，确认回归通过，再试 `xnu-sd`。

回滚：用第 2 步的快照，经守卫（同样带 `--replace-protected` 与证据）恢复 `unixnu.toml`。

## 9. 通过判据必须分层（原来把五件事混在一起了）

| 层 | 要证明的事 | 判据 | 失败说明什么 |
|---|---|---|---|
| L1 设备枚举 | UEFI 发现了存储设备 | 菜单/固件能看到新卷 | UEFI 无 SD 驱动或卡未被供电 |
| L2 文件系统协议 | UEFI 能读 FAT32 | 菜单能列出 `xnu-sd` 指向的目录/文件 | FAT 驱动或分区表问题 |
| L3 卷标识 | UniXNU 能唯一定位该卷 | 条目解析出的卷句柄/路径非空 | 卷标识解析问题 |
| L4 文件读取 | DarwinBoot 读到 `kernel.macho` 与 `.adt` | 日志出现读取成功，长度与 `DEPLOYED.txt` 的 SHA-256 一致 | 路径/权限/长度问题 |
| L5 内核一致性 | 读到的内核与手机现有的一致 | SHA-256 相等 | 拷贝错误或版本不匹配 |
| L6 hand-off | 真机完成交接 | `DARWINBOOT: hand-off to the kernel` + 页内 `entry words 140006F5` | 前五层都过了才会到这层 |

**只有 L6 通过并且有照片，才可以把"microSD 载荷路径"记为已验证。** L1–L5 各自单独记录，失败时按层定位。
