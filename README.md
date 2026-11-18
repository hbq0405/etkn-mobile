# ETKN Mobile 发布镜像

安卓手机端由 **[Alumos](https://github.com/Alumos)** 开发，原项目是 [Alumos/etkn-mobile](https://github.com/Alumos/etkn-mobile)。

**[下载 APK](https://github.com/hbq0405/etkn-mobile/releases/latest)** · [上游发布](https://github.com/Alumos/etkn-mobile/releases) · [应用源码与构建说明](https://github.com/Alumos/etkn-mobile)

本仓库只同步上游已经发布的 Release、原始 APK 和 SHA256SUMS.txt，不构建或重新签名应用，不镜像应用的源码分支。每个 Release 标明原作者、上游发布页及对应版本源码地址；应用遵循原项目 GPL-3.0 许可。GitHub 自动生成的本仓库 Source code 包仅包含同步脚本，应用源码请使用 Release 正文中的上游对应源码链接。

## 自动同步

GitHub Actions 每 5 分钟检查一次（UTC 第 3、8、13、18、23、28、33、38、43、48、53、58 分钟），也可以在 Actions 中手动运行。GitHub 调度可能延迟；工作流通过并发锁避免重复运行。

- 同步所有已发布版本及其预发布标记；草稿不公开，未包含有效 APK 的版本等待下次运行。
- 原样保存上游 APK 和校验文件，下载后及上传后均核对 SHA-256 和大小。
- 复制与校验完成后才公开 Release；失败会让工作流报错，下一次继续。上游删除的历史版本保留，不自动删除。
- 使用既有 ETK/TV 发版机器人和群，新版本发送原始更新日志、镜像下载页和上游链接。历史回填只通知初始最新版本。
- 已确认发送的版本记录 Telegram message_id，普通重复运行不会重发；若消息发送成功后 GitHub 状态保存失败，重跑可能再次通知。

仓库 Secrets：`TELEGRAM_TOKEN`、`TELEGRAM_TO`。仓库变量 `NOTIFY_FROM` 是初次启用时最新上游 Release 的 UTC 发布时间，早于此时间的历史版本不通知。同步使用当前仓库的 `GITHUB_TOKEN`，不保存个人 GitHub Token。

公开仓库长期无活动时，GitHub 可能暂停定时工作流；可在 Actions 页面重新启用。通知凭据只保存在 GitHub Secrets。

本地只读预演：设置 `GITHUB_REPOSITORY=hbq0405/etkn-mobile`、`NOTIFY_FROM`，运行 `python scripts/sync_releases.py --dry-run`。测试：`python -m unittest discover -s tests -v`。