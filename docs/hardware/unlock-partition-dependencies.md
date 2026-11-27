# 解锁补丁依赖：EFIESP / MainOS 上哪些东西不能丢

只读审计，2026-11-27。目的：判断 **MainOS 能否格式化** 而不丢失 WOA 解锁。**本文件结论是"不能"，理由如下。**

## 1. 已知事实（来自仓库记录与本会话实测）

| 事实 | 来源 |
|---|---|
| 解锁补丁**同时涉及 EFIESP 与 MainOS** | `scripts/phone-image.py` 文件头注释（"the two partitions the unlock patches live on"） |
| 两分区必须**一起**恢复 | `docs/hardware/2026-11-25-unlocked-partition-images.md`：只恢复 EFIESP 而 MainOS 仍带补丁 → 齿轮循环 |
| 解锁状态与 **bootarm.efi** 有关 | `docs/hardware/handset-boot-chain.md`：解锁后的 boot manager 才去找 `\UEFI.elf` |
| 解锁需要一个 **950 XL donor FFU / AddFFU** 才能解析参考版本 | `docs/hardware/2026-11-25-woa-ffu-reference.md` 与机主工具经验 |
| 当前 MainOS 承载内核载荷 `EFI\UniXNU\Payloads\kernel.macho(+.adt)` | 本会话实测：`H:\EFI\UniXNU\Payloads\` |
| MainOS 现在**没有** Apple 根卷；是 NTFS 的 Windows OS 分区 | 同上（`H:` 为 MainOS，约 29.5 GB） |

## 2. 解锁补丁具体改了哪些东西——**尚未逐项确认**

必须说清楚：仓库目前**没有**"解锁补丁逐扇区清单"这种证据。已知的只是"两个分区都被改过"，具体到文件/扇区是空白。因此：

| 问题 | 现状 |
|---|---|
| EFIESP 上哪些文件/扇区被解锁工具改过 | **未确认**（可对比原厂 FFU 的 EFIESP 与当前 EFIESP，但需要原厂镜像，本轮未做） |
| MainOS 上哪些文件/扇区被改过 | **未确认** |
| 只保留解锁补丁、删除 Windows 内容是否可行 | **无法判断**，见第 3 节 |
| 能否用"只含解锁状态"的分区镜像恢复 | 理论上可以（`phone-image.py restore --partition`），但**该路径尚未实机验证** |

## 3. 为什么"格式化 MainOS"现在不能做

1. **解锁补丁的落点未知**：如果补丁在 MainOS 的引导文件（`\Windows\System32\Boot\bootshim.efi` 一类）或 BCD 相关文件上，格式化会直接毁掉解锁链。
2. **bootarm.efi 与 MainOS 的耦合未验证**：解锁后的 boot manager 找 `\UEFI.elf`（在 EFIESP 根），但它的"解锁状态"是否还依赖 MainOS 上的某个文件，目前没有证据。
3. **唯一的回滚是整分区镜像**，而 EFIESP 镜像的现状与文档不符（见 `boot-chain-preservation.md` 第 4 节）。在这种状态下动 MainOS，等于把仅有的回滚路径也变成不确定的。
4. **不可逆性不对称**：格式化 MainOS 会毁掉 Windows 回退路径与可能存在的解锁状态；而收益只是"多一个卷"。用可逆方案（microSD / 独立 FAT32 分区 / 卷内目录）能达到同样目的。

## 4. 可逆的替代路径（推荐顺序）

| 方案 | 是否动 MainOS | 是否影响解锁 | 需要先证明什么 |
|---|---|---|---|
| A. 在 MainOS 的 NTFS 上继续放载荷（现状） | 否 | 否 | 已验证：DarwinBoot 通过 `ntfs.efi` 读到 `kernel.macho` |
| B. microSD 上放载荷 | 否 | 否 | UEFI 能枚举 SD、UniXNU 能访问该卷、DarwinBoot 能找到并读取 |
| C. EFIESP 内新增目录放载荷 | 否（但 EFIESP 仅 32 MB） | 否 | 空间与 FAT 限制；内核 18.9 MB 是否能放下 |
| D. 缩小/新建分区（保留 MainOS 引导区，仅释放尾部空间） | **是（部分）** | 未知风险 | 必须先有原厂 EFIESP/MainOS 对照镜像与一次成功恢复 |
| E. 整盘重排/格式化 MainOS | 是 | **高风险** | 需要完整的解锁补丁清单 + 已验证恢复路径 |

**结论：D/E 在拿到"解锁补丁清单 + 恢复路径实机验证"之前，一律不执行。**

## 5. 要把这件事推进到可决策，需要的最小证据集

1. 原厂（未解锁）FFU 的 EFIESP / MainOS 各一份**只读**镜像，与当前解锁态逐扇区对比 → 得到解锁补丁的落点清单。
2. 一次 `phone-image.py restore --partition {EFIESP,MainOS}` 的**实机验证**（用当前两份镜像，成对恢复），证明"分区镜像可以恢复解锁状态"。
3. 确认 `bootarm.efi` / `\UEFI.elf` / BCD 三者的解锁依赖关系（替换实验的失败记录已有：替换 bootarm 会导致 mass storage 都进不去）。

在第 1、2 项完成之前，任何"格式化 MainOS"的计划都应视为**不可回滚操作**。
