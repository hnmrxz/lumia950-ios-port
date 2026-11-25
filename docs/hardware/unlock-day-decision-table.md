# 解锁当天的判定表

一张表，判定"这次开机走到哪、下一步做什么"。左列是能看到的输出，右列是唯一动作。表中的字符串都来自本
仓库的代码或文档，出现与不出现都可以机械判断。

## 一、上电后第一屏

| 看到 | 含义 | 动作 |
|---|---|---|
| Windows 徽标 / 转圈 / 两个齿轮 | 固件没走 `{default}`：仍然启动 WOA | 回到 `check-bcd-layout.py`，先确认 `{bootmgr} path` 与 `{default}` 三层 |
| 黑屏无输出超过 60 s | shim 不是 `0x0A`，或 `\Windows\System32\Boot\bootshim.efi` 不存在 | 用 `phone-install.py --verify-bcd` 复核；确认 PE subsystem |
| `UniXNU` 菜单（4 个条目，默认 `xnu`） | **链已到达 UniXNU** | 进入第二节 |

## 二、菜单之后

| 看到 | 含义 | 动作 |
|---|---|---|
| 菜单 1 s 后自动启动 `xnu` | 超时自动启动生效，属正常 | 观察下一屏 |
| `DARWINBOOT: loader v2 installed EL1` | DarwinBoot 已接管，准备好交接 | 记录这一行，作为 `EFI-tested` 升级证据 |
| `DARWINBOOT: hand-off to the kernel` | 交接完成（**真机上的关键分界**） | 进入第三节 |
| 停在菜单不超时 | `unixnu.toml` 里 timeout 配置与预期不符 | 重新由 `stage-kernel.py` 生成，不要手改 |

## 三、交接之后

| 看到 | 含义 | 动作 |
|---|---|---|
| 内核早期横幅（如 `arm_vm_init`） | XNU 已开始执行 | 记录为 `XNU-entry-tested` 证据 |
| `!BSD` | BSD 初始化返回（与 QEMU 一致） | 记录，然后等根设备 |
| `Still waiting for root device` | 与仿真同一停点：缺可用的块设备/文件系统 | 这是 `NativeSdhci` 的活，见 `docs/storage-bringup.md` |
| 无任何输出 | 交接后死机（与合并镜像在 QEMU 中同样的症状） | 先怀疑内核加载地址/ADT，再看 `DarwinBoot` 打印的 pa/va/args |

## 四、无论走到哪，先做这件事

把 `EFIESP` 与 `MainOS` 的**分区镜像**抓下来（`phone-image.py dump`），再动任何东西。这样"下一次尝试"
不会以一次完整 FFU 刷机为代价。

## 五、这张表如何演进

每出现一次新输出，就把它加进第三节并注明日期与证据标签。表里没有的行，说明还没观测到——**不要凭推测
补一行**。
